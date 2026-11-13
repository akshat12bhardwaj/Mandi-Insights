"""Idempotent daily publication with structured logs and last-success retention."""
from datetime import timedelta
import json
import os
import socket
import uuid
import shutil
from Code.daily import operational as op
from Code.daily.dataset import OUT as DAILY,write_json,sha
from Code.daily.policy import now_ist
from . import ingestion
from .build import OUT
from .coverage import audit
from .service import catalog
from .discovery import discover
from .learning import enqueue as enqueue_learning

STATE=OUT/'phase2'


def publish_serving_snapshot():
    """Commit prices, catalog and derived views through one atomic pointer."""
    from .explanations import QUALITY
    batch=json.loads((DAILY/'batch.json').read_text())
    folder=DAILY/'intelligence_publications'/batch['sha256']
    folder.mkdir(parents=True,exist_ok=True)
    paths={'coverage':STATE/'coverage.json','status':STATE/'status.json','last_success':STATE/'last_success.json','strategies':STATE/'strategies.json','quality':QUALITY}
    auxiliary={}
    for name,path in paths.items():
        if path.exists():
            destination=folder/(name+'.json')
            if destination.exists() and destination.read_bytes()!=path.read_bytes():
                # An unchanged price batch may have a newly verified quality or
                # config view. Retain the previous immutable publication too.
                destination=folder/(name+'-'+sha(path)[:12]+'.json')
            if not destination.exists():
                temporary=destination.with_suffix('.tmp')
                shutil.copyfile(path,temporary);temporary.replace(destination)
            auxiliary[name]=str(destination.relative_to(DAILY))
    write_json(DAILY/'serving.json',{'release':json.loads((DAILY/'release.json').read_text()),'batch':batch,
                                  'batch_pointer_sha256':sha(DAILY/'batch.json'),'auxiliary':auxiliary})


def process_alive(pid):
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle:
            if ctypes.get_last_error()==87:return False
            raise ValueError('Cannot verify the existing refresh lock owner')
        code=ctypes.c_ulong()
        try:
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code)):raise ValueError('Cannot query refresh lock owner')
            return code.value==259
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(int(pid),0);return True
    except ProcessLookupError:return False


def acquire_lock(lock):
    if lock.exists():
        held=lock.read_bytes()
        try:owner=json.loads(held)
        except ValueError:raise ValueError('Existing legacy refresh lock requires inspection') from None
        if owner.get('host')!=socket.gethostname() or process_alive(owner['pid']):raise ValueError('Another refresh owns the lock')
        if lock.read_bytes()!=held:raise ValueError('Refresh lock changed while checking its owner')
        lock.unlink()  # Only a verified dead process on this host can be recovered.
        event('recovered_interrupted_lock')
    with lock.open('x',encoding='utf-8') as f:
        json.dump({'pid':os.getpid(),'host':socket.gethostname(),'started_at':now_ist().isoformat(),'token':uuid.uuid4().hex},f)


def event(kind,**values):
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'refresh.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':now_ist().isoformat(),'event':kind,**values},ensure_ascii=False)+'\n')


def run(lookback=7,budget=280,max_mb=50,execute=False,batch_only=False,backfill=False,collector=None,crops=None):
    if not 1<=lookback<=730 or budget<1 or max_mb<1:raise ValueError('Invalid refresh limits')
    end=now_ist().date();start=end-timedelta(days=lookback-1)
    inventory=discover()
    supported=[r['crop'] for r in inventory.get('discovery',inventory['crops'])]
    source_manifest=DAILY/'refresh_manifest.json'
    established=sorted({p['crop'] for p in json.loads(source_manifest.read_text())['partitions'].values()}) if source_manifest.exists() else [r['crop'] for r in catalog()['crops']][:8]
    crops=[ingestion.crop_name(c) for c in crops] if crops else established
    if not set(crops)<=set(supported):raise ValueError('Unsupported collection crop')
    plan={'start':str(start),'end':str(end),'crops':crops,'request_budget':budget,'byte_budget':max_mb*1_000_000,
          'pagination':True,'retry_attempts':3,'recheck_late_reports':not backfill,
          'scheduler_status':'Inspect Windows Task Scheduler for registration and runtime state'}
    if not execute and not batch_only:return plan
    lock=DAILY/'update.lock'
    acquire_lock(lock)
    from Code.api import daily
    building=None
    try:
        if not (DAILY/'serving.json').exists() and (DAILY/'release.json').exists() and (DAILY/'batch.json').exists():publish_serving_snapshot()
        from Code.api import daily
        building=daily.BUILDING.set(True)
        saved={name:(DAILY/name).read_bytes() if (DAILY/name).exists() else None for name in ('release.json','batch.json','serving.json')}
        derived=[STATE/name for name in ('coverage.json','coverage.csv','operational_view.json','strategies.json','last_success.json')]
        from .explanations import QUALITY
        derived+=[QUALITY,OUT/'phase3/future_batch.json']
        saved_derived={path:path.read_bytes() if path.exists() else None for path in derived}
        event('started',batch_only=batch_only,backfill=backfill)
    except Exception:
        if building is not None:daily.BUILDING.reset(building)
        lock.unlink()
        raise
    try:
        result={'status':'offline','new_records':0,'accepted':0,'errors':[]}
        if not batch_only:
            collect=collector or ingestion.collect
            result=collect(start,end,crops,budget,max_mb*1_000_000,recheck=not backfill)
        held=json.loads(saved['batch.json']) if saved['batch.json'] else {}
        before=json.loads(saved['release.json']) if saved['release.json'] else {}
        if result['status']=='partial_provider_failure' and not result.get('accepted') and held.get('target_date')==str(end):
            status={'status':'failed_previous_snapshot_retained','attempt_at':now_ist().isoformat(),
                    'errors':result['errors'],'collection':result,'last_success_preserved':True}
            write_json(STATE/'status.json',status);event('failed',reason='provider_unavailable');return status
        dest,manifest=op.release(publish=False,catalog_override=discover())
        after={'release':dest.name,'manifest_sha256':sha(dest/'manifest.json')}
        changed=before!=after or held.get('target_date')!=str(end)
        if changed:
            op.batch(release_bundle=(dest,manifest));write_json(DAILY/'release.json',after)
        from Code.api import daily
        daily._snapshot.cache_clear()
        report=audit()
        from . import service
        service.archive.cache_clear()
        from .explanations import build_quality
        build_quality()
        from .future import batch as future_batch
        future_count=future_batch()
        strategies,count=service.strategies()
        learning_jobs=enqueue_learning()
        write_json(STATE/'strategies.json',{'batch_signature':sha(DAILY/'batch.json'),'config_signature':service.config_signature(),'date':str(end),'rows':strategies,'candidate_count':count})
        status={'status':'partial_update' if result['status'].startswith('partial') or result.get('errors') else 'updated' if changed else 'unchanged',
                'attempt_at':now_ist().isoformat(),'successful_publication_at':now_ist().isoformat(),
                'batch_issue':json.loads((DAILY/'batch.json').read_text())['issue'],
                'latest_source_observation':max((r['last_observation'] for r in report['rows'] if r['recent_source_records']),default=None),
                'new_record_count':result.get('new_records',0),'forecast_count':report['forecast_count'],
                'eligible_crop_count':report['eligible_crop_count'],'strategy_count':count,'future_forecast_count':future_count,'learning_jobs_queued':learning_jobs,'collection':result,'errors':result.get('errors',[])}
        write_json(STATE/'last_success.json',status);write_json(STATE/'status.json',status)
        publish_serving_snapshot()
        event('published',status=status['status'],forecasts=report['forecast_count'],eligible_crops=report['eligible_crop_count'])
        return status
    except Exception as exc:
        for path,content in saved_derived.items():
            if content is not None:
                temporary=path.with_suffix('.restore.tmp');temporary.write_bytes(content);temporary.replace(path)
            elif path.exists():path.unlink()
        for name,content in saved.items():
            if content is not None:
                temp=DAILY/(name+'.restore.tmp');temp.write_bytes(content);temp.replace(DAILY/name)
            elif (DAILY/name).exists():(DAILY/name).unlink()
        write_json(STATE/'status.json',{'status':'failed_previous_snapshot_retained','attempt_at':now_ist().isoformat(),
                                      'error_type':type(exc).__name__,'file':os.path.basename(exc.filename) if isinstance(exc,OSError) and exc.filename else None,
                                      'reason':'Refresh failed; previous published batch retained.','last_success_preserved':True})
        event('failed',error_type=type(exc).__name__)
        raise
    finally:
        daily.BUILDING.reset(building)
        lock.unlink()
