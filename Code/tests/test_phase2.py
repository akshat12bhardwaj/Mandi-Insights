from datetime import date
import json
from pathlib import Path
import requests
import pytest
from Code.intelligence import ingestion as i,pipeline as p
from Code.daily.dataset import write_json


def row(market='M',price='120'):
    return {'Commodity':'Tomato','Arrival_Date':'11/11/2026','State':'S','District':'D','Market':market,
            'Variety':'Other','Grade':'FAQ','Min_Price':'100','Max_Price':'200','Modal_Price':price}


def client(tmp_path,fetch,budget=20):
    return i.Client(budget,1_000_000,tmp_path/'usage.json',fetch=fetch,sleep=lambda _:None,page_size=2)


def test_pagination_and_double_pass(tmp_path):
    calls=[];data=[row(str(n)) for n in range(5)]
    c=client(tmp_path,lambda crop,day,offset,limit:calls.append(offset) or {'total':5,'records':data[offset:offset+limit]})
    rows,fingerprint=c.partition('Tomato',date(2026,11,11))
    assert len(rows)==5 and len(fingerprint)==64
    assert calls==[0,2,4,0,2,4]


def test_repeated_pages_rejected(tmp_path):
    c=client(tmp_path,lambda *a:{'total':4,'records':[row('A'),row('B')]})
    with pytest.raises(ValueError,match='Repeated page'):c.partition('Tomato',date(2026,11,11))


def test_source_identity_conflicts_are_kept_for_cleaner(tmp_path):
    c=client(tmp_path,lambda *a:{'total':2,'records':[row(price='120'),row(price='130')]})
    assert len(c.partition('Tomato',date(2026,11,11))[0])==2


def test_retry_and_failed_calls_consume_budget(tmp_path):
    calls=[]
    def fetch(*args):
        calls.append(1)
        if len(calls)<3:raise requests.Timeout()
        return {'total':0,'records':[]}
    c=client(tmp_path,fetch)
    assert c.page('Tomato',date(2026,11,11),0)['total']==0
    assert c.usage['calls']==3 and c.usage['retries']==2
    c=client(tmp_path,lambda *a:(_ for _ in ()).throw(requests.Timeout()),budget=3)
    with pytest.raises(i.BudgetExceeded):c.page('Tomato',date(2026,11,11),0)


def test_no_missing_zero_or_wrong_commodity(tmp_path):
    for body in [{},{'records':[],'total':False}]:
        c=client(tmp_path,lambda *a,b=body:b)
        with pytest.raises(ValueError):c.page('Tomato',date(2026,11,11),0)
    with pytest.raises(ValueError):i.validate_record({**row(),'Commodity':'Onion'},'Tomato',date(2026,11,11))
    with pytest.raises(ValueError):i.validate_record({**row(),'Price_Unit':'INR/kg'},'Tomato',date(2026,11,11))
    assert i.crop_name('Common Paddy')=='Paddy(Dhan)(Common)'
    assert i.crop_name('Paddy(Common)')=='Paddy(Dhan)(Common)'
    assert i.SOURCE_NAMES['Paddy(Dhan)(Common)']=='Paddy(Common)'
    assert i.crop_name('Rice')!='Paddy(Dhan)(Common)'


def test_incremental_idempotence_and_partial_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(i,'ROOT',tmp_path);monkeypatch.setattr(i,'OUT',tmp_path/'out');monkeypatch.setattr(i,'RAW',tmp_path/'raw')
    fetch=lambda *a:{'total':1,'records':[row()]}
    args=(date(2026,11,11),date(2026,11,11),['Tomato'],4,1_000_000)
    a=i.collect(*args,fetch=fetch,recheck=False,sleep=lambda _:None)
    assert a['new_records']==1
    assert i.collect(*args,fetch=lambda *a:pytest.fail('Already collected'),recheck=False)['calls']==0
    old=list((tmp_path/'raw').rglob('*.json'))[0].read_bytes()
    b=i.collect(*args,fetch=fetch,recheck=True,sleep=lambda _:None)
    assert b['new_records']==0
    assert list((tmp_path/'raw').rglob('*.json'))[0].read_bytes()==old


def isolate(monkeypatch,tmp_path):
    monkeypatch.setattr(p,'OUT',tmp_path/'intelligence')
    monkeypatch.setattr(p,'publish_serving_snapshot',lambda:None)
    monkeypatch.setattr(p,'enqueue_learning',lambda:0)
    from Code.intelligence import explanations
    monkeypatch.setattr(explanations,'QUALITY',tmp_path/'quality.json')
    monkeypatch.setattr(p,'DAILY',tmp_path/'daily');p.DAILY.mkdir()
    monkeypatch.setattr(p,'STATE',tmp_path/'state')
    monkeypatch.setattr(p,'catalog',lambda:{'crops':[{'crop':'Tomato'}]})
    monkeypatch.setattr(p,'discover',lambda:{'crops':[{'crop':'Tomato'}]})
    for name in ('release.json','batch.json'):write_json(p.DAILY/name,{'target_date':str(p.now_ist().date()),'release':'old'})


def test_failure_retains_pointers_and_last_success(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    write_json(p.STATE/'last_success.json',{'successful_publication_at':'previous'})
    held={f.name:f.read_bytes() for f in p.DAILY.glob('*.json')}
    monkeypatch.setattr(p.op,'release',lambda **k:(_ for _ in ()).throw(ValueError('Synthetic fail')))
    with pytest.raises(ValueError):p.run(batch_only=True)
    assert all((p.DAILY/n).read_bytes()==content for n,content in held.items())
    assert json.loads((p.STATE/'last_success.json').read_text())['successful_publication_at']=='previous'
    assert not (p.DAILY/'update.lock').exists()


def test_provider_failure_preserves_current_publication(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    status=p.run(execute=True,collector=lambda *a,**k:{'status':'partial_provider_failure','accepted':0,'errors':[{'reason':'timeout'}]})
    assert status['status']=='failed_previous_snapshot_retained'
    assert not (p.STATE/'last_success.json').exists()


def test_success_records_counts_and_second_publication_is_idempotent(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    dest=tmp_path/'release';dest.mkdir();write_json(dest/'manifest.json',{})
    monkeypatch.setattr(p.op,'release',lambda **k:(dest,{}))
    calls=[]
    def batch(**kwargs):
        calls.append(1);write_json(p.DAILY/'batch.json',{'target_date':str(p.now_ist().date()),'issue':p.now_ist().isoformat()})
    monkeypatch.setattr(p.op,'batch',batch)
    monkeypatch.setattr(p,'audit',lambda:{'rows':[{'recent_source_records':1,'last_observation':'2026-11-11'}],'forecast_count':1,'eligible_crop_count':1})
    from Code.intelligence import service
    from Code.intelligence import explanations
    from Code.intelligence import future
    monkeypatch.setattr(future,'batch',lambda:0)
    monkeypatch.setattr(explanations,'build_quality',lambda:0)
    monkeypatch.setattr(service,'strategies',lambda:([],0))
    a=p.run(batch_only=True);b=p.run(batch_only=True)
    assert a['forecast_count']==1 and a['eligible_crop_count']==1
    assert len(calls)==1 and b['status']=='unchanged'
    assert json.loads((p.STATE/'last_success.json').read_text())['batch_issue']==a['batch_issue']


def test_live_lock_is_not_removed_and_dead_lock_is_recovered(monkeypatch,tmp_path):
    lock=tmp_path/'update.lock';monkeypatch.setattr(p,'STATE',tmp_path/'state')
    write_json(lock,{'host':p.socket.gethostname(),'pid':99999})
    monkeypatch.setattr(p,'process_alive',lambda _:True)
    with pytest.raises(ValueError,match='owns'):p.acquire_lock(lock)
    assert lock.exists()
    monkeypatch.setattr(p,'process_alive',lambda _:False)
    p.acquire_lock(lock)
    assert json.loads(lock.read_text())['pid']==p.os.getpid()


def test_scheduler_definition_is_opt_in_and_uses_project_directory():
    text=Path('Code/intelligence/install_scheduler.ps1').read_text()
    assert '[switch]$Install' in text and 'if ($Install)' in text
    assert "'22:30'" in text and 'India Standard Time' in text
    assert '-WorkingDirectory $projectRoot' in text and 'IgnoreNew' in text
    assert 'RestartCount 3' in text and 'StartWhenAvailable' in text


def test_price_training_has_protected_window_boundary():
    from Code.intelligence.models import PROTOCOL,DEST
    assert PROTOCOL['train_end']=='2016-12-31' and PROTOCOL['confirmation_year']==2018
    assert 'phase2' in str(DEST)


def test_fitted_candidates_have_reproducible_features_and_safe_inference():
    import numpy as np
    from Code.daily.forecast import fit_models,learned_predictions,FEATURES
    rng=np.random.default_rng(711)
    x=rng.normal(size=(80,len(FEATURES)));target=np.zeros(80)
    models=fit_models(x,target)
    predicted=learned_predictions(models,x[:3],[1000,1100,1200])
    assert set(predicted)=={'ridge','hist_gradient_boosting'}
    assert all(np.isfinite(v).all() and len(v)==3 for v in predicted.values())


def test_backfill_checks_span_anchor_first(tmp_path,monkeypatch):
    monkeypatch.setattr(i,'ROOT',tmp_path);monkeypatch.setattr(i,'OUT',tmp_path/'out');monkeypatch.setattr(i,'RAW',tmp_path/'raw')
    calls=[]
    result=i.collect(date(2026,11,1),date(2026,11,11),['Tomato'],2,1_000_000,fetch=lambda crop,day,*a:calls.append(day) or {'total':0,'records':[]},recheck=False,sleep=lambda _:None)
    assert calls==[date(2026,11,1)]*2
    assert result['status']=='partial_budget'


def test_geocoding_requires_exact_country_state_and_locality():
    from Code.intelligence.geocode import choose
    place={'id':1,'name':'Darjeeling','country_code':'IN','admin1':'West Bengal','latitude':27.033,'longitude':88.267,'feature_code':'PPL'}
    assert choose([place],'West Bengal','Darjeeling')==place
    assert choose([{**place,'country_code':'PK'}],'West Bengal','Darjeeling') is None
    assert choose([place],'Haryana','Darjeeling') is None
    assert choose([place],'West Bengal','Another town') is None
    assert choose([place,{**place,'latitude':28}],'West Bengal','Darjeeling') is None


def test_network_byte_cap_stops_before_reading_past_remaining_budget(tmp_path,monkeypatch):
    import io
    c=client(tmp_path,lambda *a:None)
    c.fetch=None;c.key='test-key';c.byte_budget=10
    class Raw:
        def __init__(self):self.data=io.BytesIO(b'x'*100)
        def read(self,size,decode_content=True):return self.data.read(size)
    class Response:
        status_code=200;raw=Raw()
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(c.session,'get',lambda *a,**k:Response())
    with pytest.raises(i.BudgetExceeded):c.page('Tomato',date(2026,11,11),0)
    assert c.usage['bytes']==10


def test_rate_limit_creates_cooldown_without_immediate_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(i,'OUT',tmp_path)
    c=client(tmp_path,lambda *a:None);c.fetch=None;c.key='test-key'
    class Response:
        status_code=429;headers={'Retry-After':'600'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(c.session,'get',lambda *a,**k:Response())
    with pytest.raises(i.ProviderFailure,match='rate limit'):c.page('Tomato',date(2026,11,11),0)
    assert c.usage['calls']==1 and c.usage['retries']==0
    assert json.loads((tmp_path/'phase2_rate_limit.json').read_text())['until']>i.now_ist().isoformat()


def test_active_cooldown_prevents_any_new_provider_request(tmp_path,monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(i,'OUT',tmp_path);monkeypatch.setattr(i,'load_key',lambda _: 'test-key')
    write_json(tmp_path/'phase2_rate_limit.json',{'until':(i.now_ist()+timedelta(hours=1)).isoformat()})
    with pytest.raises(i.ProviderFailure,match='cooldown'):i.Client(10,1000,tmp_path/'usage.json')
