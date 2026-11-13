"""Evidence and future decisions; synthetic inputs avoid protected evaluations."""
from datetime import timedelta
import copy
import json
import numpy as np
import pandas as pd
import pytest
from Code.daily.dataset import write_json,sha
from Code.daily.policy import now_ist
from Code.intelligence import explanations as ex,future,roads,service as s
from Code.tests.test_intelligence import pair


def scenario():
    buy,sell=pair()
    for row in (buy,sell):row['data_freshness']={'age_days':1,'observations':250}
    return s.calculate(buy,sell,100,'Medium truck',18,1)


def test_lower_margin_can_win_with_stronger_route_evidence(monkeypatch):
    monkeypatch.setattr(ex,'quality_for',lambda _:None)
    a=scenario();a.update(margin=1000,transport=1000,uncertainty_screen=100)
    a['route']={**a['route'],'basis':'Saved road route','objective':'shortest'}
    b=copy.deepcopy(a);b.update(margin=1100);b['route'].update(basis='Approximate distance scenario',objective='approximate')
    ex.assess(a,s.CONFIG['decision']);ex.assess(b,s.CONFIG['decision'])
    assert a['margin']<b['margin'] and a['risk_adjusted_margin']>b['risk_adjusted_margin']
    assert a['data_quality']['confidence_percentage'] is None
    comparison=ex.comparison(a,b)
    assert comparison['margin_difference']==-100
    assert 'more estimated margin' in comparison['insight']


def test_ties_prefer_supported_route_then_lower_distance():
    def row(id,score,distance,reserve):return {'id':id,'risk_adjusted_margin':score,'route':{'km':distance},'trips':1,'logistics_reserve':reserve}
    rows=[row('high',1000,300,30),row('short',990,100,0),row('outside',800,1,0)]
    ranked,tolerance=ex.rank(rows,{'tie_absolute_rs':20,'tie_score_fraction':.01})
    assert [r['id'] for r in ranked]==['short','high','outside']
    assert tolerance==20
    assert ex.rank([],s.CONFIG['decision'])==([],0)


def test_comparison_numbers_match_economics():
    a=scenario();b=copy.deepcopy(a);b['id']='alternative';b['procurement']+=500;b['transport']+=200;b['margin']-=700;b['risk_adjusted_margin']-=700
    c=ex.comparison(a,b)
    assert c['procurement_saving']==500 and c['transport_saving']==200 and c['margin_difference']==700
    info=ex.explain(a,[a,b],100)
    assert info['alternatives'][0]['id']=='alternative'
    assert info['break_even_sale_price']==round(a['total_cost']/(a['quantity_q']*(1-a['loss_pct']/100)),2)
    assert all(c['title']!='Supply advantage' for c in info['cards'])


def test_recent_movement_and_age_increase_comparison_reserve(monkeypatch):
    monkeypatch.setattr(ex,'quality_for',lambda _:{'reports':30,'recent_step_variation_rs':100})
    a=scenario();a['uncertainty_screen']=1
    for r in (a['buy'],a['sell']):r['data_freshness']['age_days']=5
    ex.assess(a,s.CONFIG['decision'])
    assert a['forecast_reserve']==28000
    assert a['data_quality']['maximum_observation_age_days']==5


def test_future_features_do_not_read_future_target():
    dates=pd.date_range('2014-01-01','2018-12-31')
    frame=pd.DataFrame({'date':dates,'price':1000+np.arange(len(dates))*.1,'series_id':'S','state':'State'})
    rows=future.examples(frame,14)
    chosen=next(r for r in rows if r['origin']>='2017-03-01')
    changed=frame.copy();changed.loc[changed.date>chosen['origin'],'price']*=2
    updated=next(r for r in future.examples(changed,14) if r['origin']==chosen['origin'])
    np.testing.assert_array_equal(chosen['x'],updated['x'])
    assert updated['actual']==chosen['actual']*2
    assert pd.Timestamp(chosen['date'])-pd.Timestamp(chosen['origin'])==pd.Timedelta(days=14)
    assert future.PROTOCOL['train_target_cutoff']<'2017-01-01'


def test_future_quote_identity_and_metric_integrity(tmp_path,monkeypatch):
    monkeypatch.setattr(future,'DEST',tmp_path);future._evaluation.cache_clear()
    pd.DataFrame([{'crop':'Onion','horizon_days':7,'model':'persistence','rows':200,'mae':50,'rmse':80}]).to_csv(tmp_path/'metrics.csv',index=False)
    write_json(tmp_path/'manifest.json',{'version':'test-future','metrics_sha256':sha(tmp_path/'metrics.csv')})
    price={'crop':'Onion','series_id':'one','target_date':str(now_ist().date()),'predicted_modal_price':1500,'last_observation_date':str(now_ist().date()-timedelta(days=1))}
    quote=future.forecast(price,7)
    assert quote['price']==1500 and quote['kind']=='future_forecast' and quote['historical_mae']==50
    assert quote['target_date']==str(now_ist().date()+timedelta(days=7))
    with pytest.raises(ValueError):future.forecast(price,10)
    with pytest.raises(ValueError):future.forecast({**price,'predicted_modal_price':None},7)
    (tmp_path/'metrics.csv').write_text('changed');future._evaluation.cache_clear()
    with pytest.raises(ValueError,match='changed'):future.forecast(price,7)


def test_directed_roads_are_not_assumed_symmetric(tmp_path,monkeypatch):
    monkeypatch.setattr(roads,'DEST',tmp_path);roads._load.cache_clear()
    pd.DataFrame([{'origin':'A','destination':'B','objective':'shortest','road_km':5,'road_hours':.1,'geometry':'[[10,70],[11,71]]'}]).to_parquet(tmp_path/'routes.parquet')
    write_json(tmp_path/'manifest.json',{'route_sha256':sha(tmp_path/'routes.parquet')})
    assert roads.saved('A','B')[0]['road_km']==5
    assert roads.saved('B','A')==[]
    assert roads.geometry('A','B','shortest')==[[10,70],[11,71]]


def test_storage_charges_handling_loss_and_directed_legs(monkeypatch):
    buy,sell=pair()
    warehouse={'warehouse_id':'W','supported_crops':['Onion'],'free_t':100,'max_days':30,'rs_q_day':1,'storage_class':'ventilated','latitude':28,'longitude':77}
    def saved(origin,destination):
        if (origin,destination) in [(buy['coordinate']['node'],'W'),('W',sell['coordinate']['node'])]:
            line = '[[28,77],[29,78]]' if destination == 'W' else '[[29,78],[30,79]]'
            return [{'objective':'shortest','road_km':20,'road_hours':1,'geometry':line}]
        return []
    monkeypatch.setattr(roads,'saved',saved)
    result=s.calculate(buy,sell,100,'Medium truck',18,1,7,warehouse)
    expected_km=40+s.CONFIG['access_km_per_endpoint']*2+s.CONFIG['warehouse_access_km']*2
    assert result['route']['km']==expected_km and result['route']['geometry']
    assert result['route']['geometry'][result['route']['stop_index']] == [29, 78]
    assert 0 < result['route']['storage_arrival_hours'] < result['route']['hours']
    assert 'Directed OSM' in result['route']['basis']
    assert result['storage']==700
    assert result['handling']==100*(18+s.CONFIG['warehouse_handling_rs_q'])
    expected_loss=100*(1-.99*(1-.002)**7)
    assert result['loss_pct']==pytest.approx(expected_loss)
    assert result['sale_revenue']==pytest.approx(round(1500*100*(1-expected_loss/100),2))


def test_live_future_and_storage_api_contract():
    from fastapi.testclient import TestClient
    from Code.api.main import app
    prices=s.current_prices()
    if not prices:pytest.skip('No current operational batch')
    client=TestClient(app);quote=client.get('/api/v4/future-price',params={'series_id':prices[0]['series_id'],'horizon':7})
    assert quote.status_code==200 and quote.json()['kind']=='future_forecast'
    rows,_=s.strategies()
    if not rows:pytest.skip('No current compatible pair')
    a=rows[0]
    response=client.post('/api/v4/storage-options',json={'buy_id':a['buy']['series_id'],'sell_id':a['sell']['series_id']})
    assert response.status_code==200
    result=response.json();assert result['rows'][0]['storage_days']==0
    assert all(r['sale_quote']['target_date']==r['schedule']['sale_at'][:10] for r in result['rows'])
    assert set(r['storage_days'] for r in result['rows'])<={0,7,14,30}


def test_forecast_mode_does_not_use_manual_price_assumption(monkeypatch):
    from Code.api.intelligence import Scenario
    from Code.intelligence.storage_decisions import calculate
    buy,sell=pair()
    warehouse={'warehouse_id':'W','supported_crops':['Onion'],'free_t':100,'max_days':30,'rs_q_day':1,'storage_class':'ventilated','latitude':28,'longitude':77}
    monkeypatch.setattr(s,'warehouses',lambda:[warehouse])
    from datetime import datetime
    from Code.daily.policy import IST
    now=datetime(2026,11,13,23,tzinfo=IST)
    monkeypatch.setattr(s,'now_ist',lambda:now)
    monkeypatch.setattr(s.lg,'node_warehouse',lambda:None)
    monkeypatch.setattr(roads,'saved',lambda *args:[])
    monkeypatch.setattr(roads,'cached_geometry',lambda *args:None)
    sell['target_date']=now.date().isoformat()
    def wrong_horizon(*args):
        pytest.fail('A seven-day storage duration is not a seven-day sale horizon')
    monkeypatch.setattr(future,'forecast',wrong_horizon)
    request=Scenario(buy_id='buy',sell_id='sell',days=7,warehouse_id='W',future_mode='forecast',future_change=99)
    result=calculate(buy,sell,request)
    assert result['sale_price']==1500 and result['sale_kind']=='persistence_assumption'
    assert result['sale_quote']['target_date']==result['schedule']['sale_at'][:10]=='2026-11-21'
    simulated=calculate(buy,sell,request.model_copy(update={'future_mode':'scenario','future_change':10}))
    assert simulated['sale_price']==1650 and simulated['sale_kind']=='scenario'



def test_storage_comparison_rejects_same_buying_and_selling_market():
    from Code.api.intelligence import Scenario
    from Code.intelligence.storage_decisions import compare
    with pytest.raises(ValueError,match='different buying and selling'):
        compare(Scenario(buy_id='same',sell_id='same'))


def test_precise_market_match_does_not_override_other_markets_or_ambiguous_district(monkeypatch):
    point={'node_id':'M:osm:1','market_key':'State|District|Market','latitude':20.1,'longitude':75.1,'precision':'OSM reported market location'}
    reference={'node_id':'D:one','state':'State','district':'District','latitude':20.,'longitude':75.}
    rows=[point,reference]
    monkeypatch.setattr(s,'nodes',lambda:rows)
    assert s.market_coordinate({'state':'State','district':'District','market':'Market'})['node']=='M:osm:1'
    assert s.market_coordinate({'state':'State','district':'District','market':'Other'})['node']=='D:one'
    rows.append({**reference,'node_id':'D:two'})
    assert s.coordinate('State','District') is None
    assert s.market_coordinate({'state':'State','district':'District','market':'Market'})['node']=='M:osm:1'


def test_separate_study_artifacts_and_covariate_availability_gates():
    from Code.intelligence import factors
    for dest,key in [(future.DEST,'artifacts'),(factors.DEST,'models')]:
        manifest_path=dest/'manifest.json'
        if not manifest_path.exists():pytest.skip('Independent retrospective study not built')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        assert sha(dest/'metrics.csv')==manifest['metrics_sha256']
        assert all(sha(dest/r['path'])==r['sha256'] for r in manifest[key])
    protocol=json.loads((factors.DEST/'protocol.json').read_text(encoding='utf-8'))
    assert protocol['production_lag_agricultural_years']>=2
    assert protocol['market_reporting_lag_assumption_days']>=3
    assert protocol['serving_promotion'] is False
    assert 'original availability vintages missing' in protocol['weather']
    metrics=pd.read_csv(factors.DEST/'metrics.csv')
    # Every ablation uses the same observed target cohort, so skill changes
    # cannot be caused by choosing easier complete-case targets per model.
    assert (metrics.groupby('crop').rows.nunique()==1).all()


def test_warehouse_cache_refreshes_on_day_or_configuration_change(monkeypatch):
    from datetime import datetime
    current={'day':'2026-11-13','signature':'first'};calls=[]
    monkeypatch.setattr(s,'now_ist',lambda:datetime.fromisoformat(current['day']))
    monkeypatch.setattr(s,'config_signature',lambda:current['signature'])
    monkeypatch.setattr(s.lg,'warehouses',lambda:pd.DataFrame([{'warehouse_id':'W'}]))
    def simulated(row,day):
        calls.append((row['warehouse_id'],day));return {'warehouse_id':row['warehouse_id'],'day':day}
    monkeypatch.setattr(s,'simulated_facility',simulated);s._warehouses.cache_clear()
    assert s.warehouses()==s.warehouses() and len(calls)==1
    current['day']='2026-11-14'
    assert s.warehouses()[0]['day']=='2026-11-14' and len(calls)==2
    current['signature']='changed'
    s.warehouses();assert len(calls)==3
    s._warehouses.cache_clear()
