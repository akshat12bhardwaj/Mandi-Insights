from datetime import date,datetime
import json
import pandas as pd
import pytest
from Code.daily import refresh as rf,operational as op
from Code.tests.test_daily_refresh import response
from Code.daily.policy import IST


def test_revision_snapshots_are_immutable_and_retracted_records_do_not_return(tmp_path,monkeypatch):
    for module in (rf,op):
        monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'OUT',tmp_path/'out')
    monkeypatch.setattr(rf,'RAW',tmp_path/'raw')
    monkeypatch.setattr(rf,'now_ist',lambda:datetime(2026,11,12,9,tzinfo=IST))
    first=response();first['records'].append({**first['records'][0],'Market':'Removed market'});first['total']=2
    args=(date(2026,11,8),date(2026,11,8),['Onion'])
    rf.collect(*args,2,1_000_000,fetch=lambda *a:first)
    manifest=json.loads((rf.OUT/'refresh_manifest.json').read_text());original=next(iter(manifest['partitions'].values()))
    original_path=tmp_path/original['path'];original_bytes=original_path.read_bytes()
    monkeypatch.setattr(rf,'now_ist',lambda:datetime(2026,11,12,10,tzinfo=IST))
    rf.collect(*args,4,1_000_000,fetch=lambda *a:response(),recheck=True)
    imported=op.import_recent('Onion')
    rows=pd.read_parquet(op.OUT/imported['storage']/'observations.parquet')
    assert len(rows)==1 and rows.iloc[0]['market']=='M'
    assert pd.Timestamp(rows.iloc[0].available_at).hour==9
    assert original_path.read_bytes()==original_bytes
    assert rf.collect(*args,4,1_000_000,fetch=lambda *a:pytest.fail('Completed scope must be idempotent'),recheck=True)['calls']==0


def test_changed_then_reverted_payload_never_overwrites_held_raw(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,'ROOT',tmp_path);monkeypatch.setattr(rf,'OUT',tmp_path/'out');monkeypatch.setattr(rf,'RAW',tmp_path/'raw')
    args=(date(2026,11,8),date(2026,11,8),['Onion'])
    for hour,price,budget in [(9,'150',2),(10,'160',4),(11,'150',6)]:
        monkeypatch.setattr(rf,'now_ist',lambda h=hour:datetime(2026,11,12,h,tzinfo=IST))
        rf.collect(*args,budget,1_000_000,fetch=lambda *a,p=price:response(p),recheck=True)
    held=list((tmp_path/'raw').rglob('*.json'))
    assert len(held)==3
    assert {json.loads(p.read_text())['retrieved_at'] for p in held}=={datetime(2026,11,12,h,tzinfo=IST).isoformat() for h in (9,10,11)}


def test_resume_does_not_spend_budget_rechecking_already_verified_scope_partitions(tmp_path,monkeypatch):
    monkeypatch.setattr(rf,'ROOT',tmp_path);monkeypatch.setattr(rf,'OUT',tmp_path/'out');monkeypatch.setattr(rf,'RAW',tmp_path/'raw')
    calls=[]
    def interrupted(crop,day):
        calls.append(day)
        if len(calls)==3:raise ValueError('synthetic provider failure')
        return {'total':0,'records':[]}
    args=(date(2026,11,7),date(2026,11,8),['Onion'],5,1_000_000)
    with pytest.raises(ValueError):rf.collect(*args,fetch=interrupted,recheck=True)
    result=rf.collect(*args,fetch=lambda c,d:calls.append(d) or {'total':0,'records':[]},recheck=True)
    assert result['total_calls_used']==5
    assert calls.count(date(2026,11,8))==2 and len(calls)==5


def test_empty_complete_partition_can_retract_a_legacy_operational_observation(tmp_path,monkeypatch):
    for module in (rf,op):
        monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'OUT',tmp_path/'out')
    monkeypatch.setattr(rf,'RAW',tmp_path/'raw')
    legacy=tmp_path/'Processed_Data/candidates/datagov_prices/dataset_v1_2/records_onion.parquet'
    legacy.parent.mkdir(parents=True)
    pd.DataFrame([{'State':'S','District':'D','Market':'M','Variety':'Other','Grade':'FAQ',
                   'reported_date':pd.Timestamp('2026-11-08'),'modal_price_rs_per_quintal':150.,
                   'retrieved_utc':'2026-11-09T00:00:00Z','record_ref':'legacy','usable_for_target':True,'in_faq_only':True}]).to_parquet(legacy,index=False)
    original=legacy.read_bytes()
    rf.collect(date(2026,11,8),date(2026,11,8),['Onion'],2,1_000_000,fetch=lambda *a:{'total':0,'records':[]})
    assert op.import_recent('Onion') is None
    assert legacy.read_bytes()==original
