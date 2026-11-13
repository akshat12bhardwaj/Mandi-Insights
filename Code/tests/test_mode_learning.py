"""Mode-scoped choices and controlled dynamic learning, without frozen targets."""
import json
import copy
import numpy as np
import pandas as pd
import pytest
from Code.daily.dataset import write_json,sha
from Code.intelligence import service as s,learning,availability,localities,explanations as ex
from Code.tests.test_dynamic_intelligence import market_prices


def test_auto_mode_is_the_top_ranked_category_and_filters_are_mode_scoped(market_prices):
    result=s.strategies(mode='auto',details=True)
    assert result['active_mode']==result['rows'][0]['trading_mode']
    assert result['groups'][result['active_mode']]['best']['id']==result['rows'][0]['id']
    intra=s.strategies(mode='intrastate',details=True)
    assert intra['filters']['crops']==['Onion']
    assert {r['id'] for r in intra['filters']['states']}=={'HR'}
    inter=s.strategies(mode='interstate',details=True)
    assert set(inter['filters']['crops'])=={'Onion','Potato'}


def test_unavailable_mode_preserves_crop_and_region(market_prices):
    result=s.strategies(crop='Potato',state='GJ',mode='intrastate',details=True)
    assert result['rows']==[] and result['effective_filters']['crop']=='Potato'
    assert result['effective_filters']['state']=='GJ'
    assert result['empty_explanation'] and 'Onion' in result['fallback_crops']
    assert s.strategies(crop='Potato',state='GJ',mode='interstate',details=True)['groups']['interstate']['best']


def test_competitors_and_comparison_use_actual_ranked_economics(market_prices):
    result=s.strategies(mode='interstate',details=True)
    group=result['groups']['interstate']
    assert [r['id'] for r in result['competitors']]==[r['id'] for r in group['rows'][1:4]]
    chosen=result['competitors'][0]
    inspected=s.strategies(mode='interstate',selected_id=chosen['id'],details=True)
    c=inspected['selected_comparison'];best=group['best']
    assert c['margin_difference']==round(chosen['margin']-best['margin'],2)
    assert inspected['groups']['interstate']['best']['id']==best['id']
    assert all(r['route']['objective']=='approximate' for r in result['rows'])


def test_availability_distinguishes_mapping_from_product_incompatibility(market_prices,monkeypatch):
    monkeypatch.setattr(s,'market_coordinate',lambda row:None if row['series_id']=='1' else row['coordinate'])
    report={r['crop']:r for r in availability.audit()}
    assert report['Onion']['raw_compatible_pairs']['intrastate']==2
    assert report['Onion']['eligible_pairs']['intrastate']==0
    assert 'location reference' in report['Onion']['reasons']['intrastate']
    assert report['Onion']['unknown_state_forecasts']==1
    assert 'No exact' in report['Potato']['reasons']['intrastate']


def test_market_locality_must_be_unambiguous():
    assert localities.town('Warangal APMC')=='Warangal'
    assert localities.town('Baruipur(Canning) APMC') is None


def test_unvalidated_error_keeps_a_conservative_exposure_screen(monkeypatch):
    from Code.tests.test_intelligence import pair
    buy,sell=pair()
    monkeypatch.setattr(ex,'quality_for',lambda _:{'reports':30,'recent_step_variation_rs':1})
    result=s.calculate(buy,sell,100,'Medium truck',18,1)
    result['uncertainty_screen']=None
    ex.assess(result,s.CONFIG['decision'])
    assert result['forecast_reserve']>=max(result['procurement'],result['sale_revenue'])*s.CONFIG['decision']['unknown_error_fraction']
    assert result['data_quality']['historical_error_available'] is False
    assert 'historical error unavailable' in result['data_quality']['label']


@pytest.fixture(scope='module')
def evaluated(tmp_path_factory):
    old=learning.DEST;learning.DEST=tmp_path_factory.mktemp('learning')
    dates=pd.date_range('2013-01-01','2018-12-31')
    h=pd.concat([pd.DataFrame({'series_id':f'S{i}','state':'Haryana','date':dates,'price':1000+i*50+np.arange(len(dates))*.1+10*np.sin(np.arange(len(dates))/30)}) for i in range(3)],ignore_index=True)
    key=learning.evaluate(h,'Synthetic new commodity','source-a','dataset-a')
    yield learning.DEST,key,h
    learning.DEST=old;learning.verified.cache_clear()


def test_separate_models_metrics_and_promotion_gates(evaluated):
    dest,key,_=evaluated;folder=dest/'runs'/key
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    scores=pd.read_csv(folder/'metrics.csv')
    assert manifest['state']=='evaluated' and manifest['serving_model']=='persistence'
    assert len(manifest['artifacts'])==4 and len(scores)==20
    assert set(scores.model)==set(learning.METHODS)
    assert set(scores.horizon_days)=={0,7,14,30}
    assert all(sha(folder/r['path'])==r['sha256'] for r in manifest['artifacts'])
    assert all(not r['eligible'] for r in manifest['promotion_gates'])
    assert manifest['dataset_version']=='dataset-a' and manifest['protocol']['last_permitted_target']=='2018-12-31'


def test_protected_and_current_target_years_do_not_affect_evaluation(evaluated,monkeypatch):
    dest,key,h=evaluated;monkeypatch.setattr(learning,'DEST',dest)
    changed=pd.concat([h,pd.DataFrame([{'series_id':'S0','state':'Haryana','date':pd.Timestamp('2026-11-13'),'price':999999999.}])],ignore_index=True)
    monkeypatch.setattr(learning,'fit_models',lambda *args:pytest.fail('Unchanged allowed history must reuse existing evaluation'))
    assert learning.evaluate(changed,'Synthetic new commodity','source-a')==key


def test_learning_evidence_checks_model_integrity(evaluated,monkeypatch):
    dest,key,_=evaluated;monkeypatch.setattr(learning,'DEST',dest)
    monkeypatch.setattr(s,'catalog',lambda:{'crops':[{'crop':'Synthetic new commodity','storage':'archive/x','observations_sha256':'source-a'}]})
    assert learning.score('Synthetic new commodity',7)['rows']>=200
    path=dest/'runs'/key/'7d.joblib';original=path.read_bytes()
    try:
        path.write_bytes(b'tampered')
        with pytest.raises(ValueError,match='artifact integrity'):learning.score('Synthetic new commodity',7)
    finally:path.write_bytes(original);learning.verified.cache_clear()


def test_dynamic_future_support_requires_evaluated_horizon(evaluated,monkeypatch):
    from Code.intelligence import future
    from Code.daily.policy import now_ist
    dest,_,_=evaluated;monkeypatch.setattr(learning,'DEST',dest)
    monkeypatch.setattr(s,'catalog',lambda:{'crops':[{'crop':'Synthetic new commodity','storage':'archive/x','observations_sha256':'source-a'}]})
    monkeypatch.setattr(learning,'fit_models',lambda *args:pytest.fail('Serving cannot train candidates'))
    monkeypatch.setattr(future,'_evaluation',lambda signature:({'version':'legacy'},pd.DataFrame(columns=['crop','horizon_days','model','rows','mae'])))
    price={'crop':'Synthetic new commodity','series_id':'new','target_date':str(now_ist().date()),'predicted_modal_price':1500,'last_observation_date':str(now_ist().date()-pd.Timedelta(days=1))}
    result=future.forecast(price,7)
    assert result['kind']=='future_forecast' and result['price']==1500
    assert result['model_version']==learning.PROTOCOL['version'] and result['validation_rows']>=200
    monkeypatch.setattr(learning,'score',lambda *args:None)
    with pytest.raises(ValueError,match='Insufficient horizon'):future.forecast(price,7)


def test_explicit_promotion_requires_yearly_skill_and_current_regime_evidence():
    table=pd.DataFrame({'year':[2017]*100+[2018]*100,'actual':[1000.]*200,'persistence':[1100.]*200,'ridge':[1001.]*200})
    assert not learning.promotion(table,'ridge')['eligible']
    assert learning.promotion(table,'ridge',current_regime_evidence=True)['eligible']
    table.loc[table.year==2018,'ridge']=1200
    assert not learning.promotion(table,'ridge',True)['eligible']


def test_queue_is_idempotent_and_source_only_history_avoids_daily_retraining(tmp_path,monkeypatch):
    monkeypatch.setattr(learning,'DEST',tmp_path/'jobs');monkeypatch.setattr(learning,'OUT',tmp_path/'intel');monkeypatch.setattr(learning,'DAILY',tmp_path/'daily')
    monkeypatch.setattr(s,'catalog',lambda:{'crops':[]})
    monkeypatch.setattr(s.daily,'snapshot',lambda:({'sources':[]},None,None,{'dataset_version':'v'}))
    entry={'crop':'New commodity','observations_sha256':'one','storage':'archive/new'}
    assert learning.enqueue([entry])==1 and learning.enqueue([entry])==0
    assert learning.enqueue([{**entry,'observations_sha256':'two'}])==1
    assert learning.enqueue([{'crop':'Source only'}])==1
    assert learning.enqueue([{'crop':'Source only','last_date':'2026-11-13'}])==0


def test_no_safe_history_never_fits_models(tmp_path,monkeypatch):
    monkeypatch.setattr(learning,'DEST',tmp_path)
    monkeypatch.setattr(learning,'fit_models',lambda *args:pytest.fail('Insufficient history cannot fit a candidate'))
    frame=pd.DataFrame({'series_id':['S'],'state':['Haryana'],'date':[pd.Timestamp('2026-11-13')],'price':[1000.]})
    key=learning.evaluate(frame,'Source only','empty')
    manifest=json.loads((tmp_path/'runs'/key/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['state']=='insufficient_safe_development_history'
    assert not manifest['artifacts'] and not manifest['serving_approved']


def test_material_source_identity_ignores_protected_recent_values(tmp_path):
    path=tmp_path/'observations.parquet'
    h=pd.DataFrame({'series_id':['S','S'],'state':['Haryana','Haryana'],'date':pd.to_datetime(['2016-01-01','2026-11-13']),'price':[1000.,2000.]})
    h.to_parquet(path);first=learning.source_only_identity(((path.name,sha(path)),),str(tmp_path))
    h.loc[h.date>'2018-12-31','price']=999999;h.to_parquet(path)
    assert learning.source_only_identity(((path.name,sha(path)),),str(tmp_path))==first
    h.loc[h.date<'2017-01-01','price']=1010;h.to_parquet(path)
    assert learning.source_only_identity(((path.name,sha(path)),),str(tmp_path))!=first
