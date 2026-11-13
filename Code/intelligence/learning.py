"""Content-addressed offline evaluations for dynamically admitted commodities.

Refresh only queues new source identities. A separate bounded worker fits and
scores candidates; serving never loads a fitted candidate automatically.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from functools import lru_cache
import joblib
import numpy as np
import pandas as pd
from Code.daily import evaluate as ev
from Code.daily.forecast import fit_models,learned_predictions,metrics,METHODS,FEATURES
from Code.daily.dataset import OUT as DAILY,write_json,sha
from Code.daily.policy import now_ist
from .build import OUT

DEST=OUT/'phase5/learning_v1'
PROTOCOL={'version':'dynamic-development-v1','train_label_end':'2016-12-28','selection_year':2017,'confirmation_year':2018,
          'last_permitted_target':'2018-12-31','reporting_delay_days':3,'market_cap':12,'horizons':[0,7,14,30],
          'features':FEATURES,'methods':METHODS,'interpretation':'Revised-archive simulation; original publication vintages unknown. Not live accuracy.',
          'promotion':'At least 5% MAE improvement in both years, >=100 rows/year, positive finite predictions, and independently verified current-regime availability evidence. Fitting alone never promotes a model.'}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

@lru_cache(maxsize=32)
def source_only_identity(sources,root):
    frames=[pd.read_parquet(Path(root)/storage,columns=['series_id','state','date','price'],filters=[('date','<=',pd.Timestamp(PROTOCOL['last_permitted_target']))]) for storage,_ in sources]
    h=pd.concat(frames,ignore_index=True).sort_values(['series_id','date']) if frames else pd.DataFrame(columns=['series_id','state','date','price'])
    return 'safe-history:'+hashlib.sha256(pd.util.hash_pandas_object(h,index=False).values.tobytes()).hexdigest()

def enqueue(entries=None):
    from . import service as s
    if entries is None:
        ready={r['crop'] for r in s.current_prices()}
        entries=[r for r in s.catalog()['crops'] if r['crop'] in ready]
    legacy=OUT/'phase2/models-v1/complete.json'
    supported=set(json.loads(legacy.read_text(encoding='utf-8'))['crop_models']) if legacy.exists() else set()
    legacy_sources={}
    if legacy.exists():
        for item in json.loads(legacy.read_text(encoding='utf-8')).get('model_artifacts',[]):
            path=legacy.parent/item['path']
            # No deserialization needed to recognize the original artifact's
            # immutable archive identity: its filename is the archive folder.
            if path.exists() and sha(path)==item['sha256']:
                legacy_sources[path.stem]=joblib.load(path)['source_sha256']
    count=0
    for entry in entries:
        entry=dict(entry)
        slug=Path(entry.get('storage','')).name
        if entry['crop'] in supported and legacy_sources.get(slug)==entry.get('observations_sha256'):continue
        if not entry.get('storage'):
            entry['evaluation_sources']=[r for r in s.daily.snapshot()[0].get('sources',[]) if r['crop']==entry['crop']]
        identity=entry.get('observations_sha256') or source_only_identity(tuple((str(Path(r['storage'])/'observations.parquet'),r['observations_sha256']) for r in entry['evaluation_sources']),str(DAILY))
        key=digest([PROTOCOL,entry['crop'],identity]);path=DEST/'requests'/f'{key}.json'
        if path.exists():continue
        write_json(path,{'key':key,'crop':entry['crop'],'entry':entry,'source_identity':identity,'dataset_version':s.daily.snapshot()[3]['dataset_version'],
                         'queued_at':now_ist().isoformat(),'state':'queued'})
        count+=1
    return count

def promotion(table,method,current_regime_evidence=False):
    checks={'current_regime_availability_verified':bool(current_regime_evidence)}
    for year in (2017,2018):
        g=table[table.year==year]
        finite=bool(len(g)>=100 and np.isfinite(g[method]).all() and (g[method]>0).all())
        checks[str(year)]=bool(finite and metrics(g.actual,g[method])['mae']<=metrics(g.actual,g.persistence)['mae']*.95)
    return {'eligible':all(checks.values()),'checks':checks}

def evaluate(history,crop,source_identity,dataset_version=None):
    """Only the allowed development slice participates, including fingerprinting."""
    from .future import examples
    h=history[history.date<=pd.Timestamp(PROTOCOL['last_permitted_target'])].copy()
    h=h.sort_values(['series_id','date'])
    fingerprint=hashlib.sha256(pd.util.hash_pandas_object(h[['series_id','state','date','price']],index=False).values.tobytes()).hexdigest()
    key=digest([PROTOCOL,crop,fingerprint]);folder=DEST/'runs'/key
    if (folder/'manifest.json').exists():return key
    pool=h[h.date<='2016-12-31'].groupby(['state','series_id'],observed=True).size().reset_index(name='n')
    pool=pool[pool.n>=365].sort_values(['n','series_id'],ascending=[False,True]);pool['state_order']=pool.groupby('state',observed=True).cumcount()
    ids=pool.sort_values(['state_order','n','series_id'],ascending=[True,False,True]).head(PROTOCOL['market_cap']).series_id
    folder.mkdir(parents=True,exist_ok=True);write_json(folder/'protocol.json',PROTOCOL)
    scores=[];breakdowns=[];artifacts=[];gates=[]
    for horizon in PROTOCOL['horizons']:
        train=[];validation=[]
        for sid in ids:
            g=h[h.series_id==sid]
            rows=examples(g,horizon) if horizon else ev.simulation_rows(g)[0]
            for row in rows:
                origin=row.get('origin',row['date'])
                if row['date']<=PROTOCOL['train_label_end']:train.append(row)
                elif origin>='2017-01-01':validation.append(row)
        if len(train)<100 or len(validation)<200:continue
        table=pd.DataFrame([{k:v for k,v in row.items() if k!='x'} for row in validation])
        table['year']=pd.to_datetime(table.date).dt.year
        if any((table.year==year).sum()<100 for year in (2017,2018)):continue
        fitted=fit_models(np.stack([r['x'] for r in train]),np.array([r['actual']/r['persistence']-1 for r in train]))
        for method,values in learned_predictions(fitted,np.stack([r['x'] for r in validation]),table.persistence).items():table[method]=values
        model_path=folder/f'{horizon}d.joblib'
        joblib.dump({'models':fitted,'features':FEATURES,'protocol':PROTOCOL,'crop':crop,'source_identity':source_identity,'development_fingerprint':fingerprint,'serving_approved':False},model_path)
        artifacts.append({'path':model_path.name,'sha256':sha(model_path)})
        for method in METHODS:
            if not np.isfinite(table[method]).all() or (table[method]<=0).any():continue
            score=metrics(table.actual,table[method]);base=metrics(table.actual,table.persistence)['mae']
            scores.append({'crop':crop,'horizon_days':horizon,'model':method,**score,'skill_pct':100*(1-score['mae']/base) if base else 0,'markets':table.series_id.nunique(),'training_rows':len(train)})
            for dimension,column in [('year','year'),('market','series_id'),('freshness','age_days')]:
                for value,g in table.groupby(column):breakdowns.append({'horizon_days':horizon,'model':method,'dimension':dimension,'value':str(value),**metrics(g.actual,g[method])})
            if method in fitted:gates.append({'horizon_days':horizon,'model':method,**promotion(table,method)})
    pd.DataFrame(scores).to_csv(folder/'metrics.csv',index=False);pd.DataFrame(breakdowns).to_csv(folder/'breakdowns.csv',index=False)
    write_json(folder/'manifest.json',{'crop':crop,'protocol':PROTOCOL,'source_identity':source_identity,'development_fingerprint':fingerprint,
               'state':'evaluated' if scores else 'insufficient_safe_development_history','serving_model':'persistence','serving_approved':False,
               'supported_series':ids.tolist(),'artifacts':artifacts,'metrics_sha256':sha(folder/'metrics.csv'),
               'breakdowns_sha256':sha(folder/'breakdowns.csv'),'promotion_gates':gates,'dataset_version':dataset_version,'completed_at':now_ist().isoformat()})
    return key

def work(max_jobs=1):
    from .pipeline import acquire_lock
    DEST.mkdir(parents=True,exist_ok=True);lock=DEST/'worker.lock'
    acquire_lock(lock)
    done=0
    try:
        for request in sorted((DEST/'requests').glob('*.json')):
            if done>=max_jobs:break
            job=json.loads(request.read_text(encoding='utf-8'));receipt=DEST/'receipts'/request.name
            if receipt.exists():continue
            entry=job['entry'];path=DAILY/entry['storage']/'observations.parquet' if entry.get('storage') else None
            sources=entry.get('evaluation_sources',[])
            valid_sources=all((DAILY/r['storage']/'observations.parquet').exists() and sha(DAILY/r['storage']/'observations.parquet')==r['observations_sha256'] for r in sources)
            if (path and path.exists() and sha(path)==job['source_identity']) or (path is None and valid_sources):
                frames=[pd.read_parquet(DAILY/r['storage']/'observations.parquet',filters=[('date','<=',pd.Timestamp(PROTOCOL['last_permitted_target']))]) for r in sources] if path is None else [pd.read_parquet(path,filters=[('date','<=',pd.Timestamp(PROTOCOL['last_permitted_target']))])]
                history=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame({'series_id':pd.Series(dtype=str),'state':pd.Series(dtype=str),'date':pd.Series(dtype='datetime64[ns]'),'price':pd.Series(dtype=float)})
                run=evaluate(history,job['crop'],job['source_identity'],job.get('dataset_version'))
                write_json(receipt,{'state':'completed','run':run,'crop':job['crop'],'source_identity':job['source_identity'],'dataset_version':job.get('dataset_version')})
            else:
                write_json(receipt,{'state':'insufficient_safe_development_history' if path is None else 'source_changed_requeue_required','crop':job['crop'],
                                   'reason':'No unchanged audited pre-2019 development source. Current baseline rules remain separate; no historical error or future support invented.'})
            done+=1
    finally:lock.unlink()
    return done

def score(crop,horizon=0):
    """Verify metric integrity before exposing historical evidence to serving."""
    from .service import catalog
    entry=next((r for r in catalog()['crops'] if r['crop']==crop),{})
    source=entry.get('observations_sha256')
    if not entry.get('storage'):
        from .service import daily
        sources=[r for r in daily.snapshot()[0].get('sources',[]) if r['crop']==crop]
        source=source_only_identity(tuple((str(Path(r['storage'])/'observations.parquet'),r['observations_sha256']) for r in sources),str(DAILY))
    aliases=set()
    for path in (DEST/'receipts').glob('*.json'):
        receipt=json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('crop')==crop and receipt.get('source_identity')==source and receipt.get('run'):aliases.add(receipt['run'])
    candidates=[]
    for path in (DEST/'runs').glob('*/manifest.json'):
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if manifest['crop']!=crop or manifest['state']!='evaluated':continue
        if manifest['source_identity']!=source and path.parent.name not in aliases:continue
        folder=path.parent
        paths=[path,folder/'metrics.csv',folder/'breakdowns.csv']+[folder/r['path'] for r in manifest['artifacts']]
        table=verified(str(folder),tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in paths))
        match=table[(table.horizon_days==horizon)&(table.model=='persistence')]
        if len(match):candidates.append((manifest['completed_at'],{**match.iloc[0].to_dict(),'version':manifest['protocol']['version'],
            'scope':manifest['protocol']['interpretation'],'period':'2017–2018','reporting_delay_days':manifest['protocol']['reporting_delay_days']}))
    return max(candidates,key=lambda r:r[0])[1] if candidates else None

@lru_cache(maxsize=32)
def verified(folder,signature):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if sha(folder/'metrics.csv')!=manifest['metrics_sha256'] or sha(folder/'breakdowns.csv')!=manifest['breakdowns_sha256']:raise ValueError('Dynamic evaluation metric integrity failure')
    if any(sha(folder/r['path'])!=r['sha256'] for r in manifest['artifacts']):raise ValueError('Dynamic model artifact integrity failure')
    return pd.read_csv(folder/'metrics.csv')

def dispatch():
    from .pipeline import process_alive
    lock=DEST/'worker.lock'
    if lock.exists() and process_alive(json.loads(lock.read_text(encoding='utf-8'))['pid']):return False
    pending=[p for p in (DEST/'requests').glob('*.json') if not (DEST/'receipts'/p.name).exists()]
    if not pending:return False
    DEST.mkdir(parents=True,exist_ok=True)
    with (DEST/'worker.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([sys.executable,'-B','-m','Code.intelligence.learning','work','--max-jobs','1'],cwd=str(OUT.parents[1]),
                         stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['enqueue','work']);parser.add_argument('--max-jobs',type=int,default=1)
    args=parser.parse_args()
    if not 1<=args.max_jobs<=56:parser.error('Choose a controlled 1–56 job allowance')
    print(json.dumps({'queued':enqueue()} if args.command=='enqueue' else {'completed':work(args.max_jobs)}))
