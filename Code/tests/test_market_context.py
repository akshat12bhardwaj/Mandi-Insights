"""Market intelligence contracts; no model fitting or protected evaluation."""
from datetime import datetime,timedelta,timezone
import pytest
import requests
from fastapi.testclient import TestClient
from Code.api.main import app
from Code.intelligence import environment as e,market_context as m,service as s
from Code.tests.test_dynamic_intelligence import market_prices
from Code.daily.dataset import write_json


def payload():
    body={'current':{'time':datetime.now(e.IST).isoformat(),'interval':900},'current_units':{},'daily':{'time':[str(e.now_ist().date()+timedelta(days=i)) for i in range(3)]},'daily_units':{}}
    for field,(_,unit,_,_) in e.CURRENT.items():body['current_units'][field]=unit;body['current'][field]=20
    for field,(_,unit,_,_) in e.DAILY.items():body['daily_units'][field]=unit;body['daily'][field]=[20,20,20]
    return body


def test_weather_codes_and_regional_map_fallback(monkeypatch):
    body = payload()
    body['current']['weather_code'] = 45
    body['current_units']['weather_code'] = 'wmo code'
    body['daily']['weather_code'] = [0, 61, 95]
    body['daily_units']['weather_code'] = 'wmo code'
    data = e.parse_weather(body)
    assert data['current']['weather_code'] == 45
    assert [day['weather_code'] for day in data['outlook']] == [0, 61, 95]
    monkeypatch.setattr(e.fc, 'enabled', lambda: True)
    monkeypatch.setattr(e, 'lookup', lambda point, *args, **kw: {'data': data, 'stale': point['lat'] != 28.61})
    response = TestClient(app).get('/api/v4/regional-weather').json()
    assert response['rows'][0]['name'] == 'Delhi' and response['rows'][0]['weather_code'] == 45
    assert len(response['rows']) == 1


def test_weather_units_current_and_three_day_coverage():
    parsed=e.parse_weather(payload())
    assert parsed['current']['kind']=='modeled_current'
    assert parsed['current']['interval_seconds']==900
    assert len(parsed['outlook'])==3
    assert 'not station' in parsed['basis']


@pytest.mark.parametrize('field,value',[('temperature_2m',float('nan')),('relative_humidity_2m',101),('wind_speed_10m',-1),('precipitation',True)])
def test_weather_rejects_invalid_current_values(field,value):
    body=payload();body['current'][field]=value
    with pytest.raises(ValueError):e.parse_weather(body)


def test_weather_rejects_wrong_units_and_nonconsecutive_days():
    body=payload();body['current_units']['temperature_2m']='°F'
    with pytest.raises(ValueError):e.parse_weather(body)
    body=payload();body['daily']['time'][1]=body['daily']['time'][0]
    with pytest.raises(ValueError):e.parse_weather(body)


def test_null_weather_is_not_zero_rain():
    body=payload();body['current']['precipitation']=None;body['daily']['precipitation_sum']=[None]*3
    parsed=e.parse_weather(body)
    assert parsed['current']['precipitation_mm'] is None
    assert parsed['outlook'][0]['rain_mm'] is None


def test_all_null_weather_does_not_claim_available_conditions():
    body=payload()
    for field in e.CURRENT:body['current'][field]=None
    for field in e.DAILY:body['daily'][field]=[None]*3
    parsed=e.parse_weather(body)
    assert parsed['current'] is None and parsed['outlook']==[]


def test_cached_weather_fallback_negative_cache_and_expiry(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'CACHE',tmp_path);calls=[]
    def fail(*args):calls.append(args);raise requests.Timeout()
    monkeypatch.setattr(e,'weather_fetch',fail)
    coord={'lat':20.,'lng':78.};path=tmp_path/f'{e.key(coord)}-weather.json'
    write_json(path,{'retrieved_at':(datetime.now(timezone.utc)-timedelta(hours=5)).isoformat(),'data':e.parse_weather(payload())})
    assert e.lookup(coord,'weather',True)['stale']
    assert e.lookup(coord,'weather',True)['stale'] and len(calls)==1
    write_json(path,{'retrieved_at':(datetime.now(timezone.utc)-timedelta(days=3)).isoformat(),'data':{}})
    assert e.lookup(coord,'weather') is None


def test_cache_success_and_malformed_failure_file(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'CACHE',tmp_path);calls=[];coord={'lat':20.,'lng':78.}
    (tmp_path/f'{e.key(coord)}-weather.failure.json').write_text('broken')
    def fetch(*args):calls.append(args);return e.parse_weather(payload())
    monkeypatch.setattr(e,'weather_fetch',fetch)
    assert not e.lookup(coord,'weather',True)['stale']
    assert e.lookup(coord,'weather',True) and len(calls)==1


def test_concurrent_context_requests_share_one_fetch(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep
    monkeypatch.setattr(e,'CACHE',tmp_path);calls=[]
    def fetch(*args):calls.append(args);sleep(.03);return e.parse_weather(payload())
    monkeypatch.setattr(e,'weather_fetch',fetch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:e.lookup({'lat':20.,'lng':78.},'weather',True),range(3)))
    assert len(calls)==1 and all(r and not r['stale'] for r in results)


def test_terrain_uses_batched_defensible_samples(monkeypatch):
    captured={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'elevation':[300,310,290,330,305]}
    def get(url,**kwargs):captured.update(kwargs);return Response()
    monkeypatch.setattr(e.requests,'get',get)
    terrain=e.terrain_fetch(20,78)
    assert terrain['elevation_m']==300 and terrain['sample_relief_m']==40
    assert len(captured['params']['latitude'].split(','))==5
    assert 'road quality' in terrain['logistics_note']
    assert 'plain' not in terrain['setting'] and 'urban' not in terrain['setting']


def test_weather_caution_does_not_adjust_price_or_reject(monkeypatch):
    parsed=e.parse_weather(payload());parsed['outlook'][1]['rain_mm']=70
    def lookup(coord,kind,fetch=False):return {'data':parsed if kind=='weather' else {'available':True,'sample_relief_m':250,'logistics_note':'Check gradients'},'stale':False,'retrieved_at':datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(e,'lookup',lookup);monkeypatch.setattr(e.fc,'enabled',lambda:True)
    context=e.context({'lat':20,'lng':78})
    assert len(context['cautions'])==2 and not context['used_in_price_model']
    assert 'automatic rejection' in context['decision_policy']


def test_no_coordinate_never_fetches_or_guesses(monkeypatch):
    monkeypatch.setattr(e.requests,'get',lambda *a,**k:pytest.fail('No location must not fetch'))
    context=e.context(None,True)
    assert not context['available'] and not context['terrain']['available']
    assert not m.warehouse_options({'coordinate':None})['rows']


def test_roles_use_current_compatible_prices_and_costs(market_prices):
    market={**market_prices[0],'coordinate':market_prices[0]['coordinate']}
    result=m.price_decision(market,market_prices,100)
    assert result['pair_count']==4 and result['peer_count']==3
    assert result['role'] in ('buy','sell','observe')
    assert result['best_buy']['freight']>0
    assert result['best_buy']['net_margin']!=result['best_buy']['adjusted_value']
    assert all(r['sell_id'] not in ('3','4') for r in result['connections'])


def test_historical_series_never_recommends_current_trade(market_prices):
    market={**market_prices[0],'series_id':'old'}
    result=m.price_decision(market,market_prices,100)
    assert result['role']=='observe' and result['best_buy'] is None
    assert result['pair_count']==0


def test_warehouse_distance_capacity_and_suitability(monkeypatch):
    monkeypatch.setattr(s,'warehouses',lambda:[{'warehouse_id':'near','latitude':20.01,'longitude':78.,'supported_crops':['Onion'],'free_t':4,'max_days':30,'rs_q_day':1.2},
        {'warehouse_id':'far','latitude':30.,'longitude':78.,'supported_crops':['Onion'],'free_t':100,'max_days':30,'rs_q_day':1.2}])
    monkeypatch.setattr(m.roads,'saved',lambda *a:[]);monkeypatch.setattr(s.lg,'node_warehouse',lambda:None)
    result=m.warehouse_options({'crop':'Onion','coordinate':{'node':'ref','lat':20.,'lng':78.}},100)
    assert len(result['rows'])==1 and result['compatible_count']==0
    row=result['rows'][0]
    assert row['compatible'] and not row['enough_capacity']
    assert row['distance_kind']=='approximate' and row['distance_km']>6
    assert row['seven_day_charge']==840


def test_decision_annotation_is_cached_only_and_preserves_economics(monkeypatch):
    calls=[]
    def context(coord,fetch=False):calls.append(fetch);return {'cautions':['Review loading'], 'terrain':{'available':True}}
    monkeypatch.setattr(e,'context',context)
    row={'buy':{'market':'Buy','coordinate':{}},'sell':{'market':'Sell','coordinate':{}},'margin':42,'risk_adjusted_margin':20,'decision':{}}
    m.scenario_contribution(row)
    assert calls==[False,False] and row['margin']==42 and row['risk_adjusted_margin']==20
    assert len(row['market_context']['cautions'])==2


def test_live_local_detail_and_filter_contracts(monkeypatch):
    # Uses accepted local artifacts only; environmental lookup remains cache-only.
    client=TestClient(app)
    markets=client.get('/api/v4/markets',params={'crop':'Onion','recent':True,'limit':10}).json()
    assert len(markets['rows'])<=10
    if not markets['rows']:pytest.skip('No current publication for today')
    row=markets['rows'][0]
    response=client.get('/api/v4/market-intelligence',params={'crop':'Onion','series_id':row['series_id']})
    assert response.status_code==200
    data=response.json();assert data['market']['series_id']==row['series_id'] and data['batch_id']==markets['batch_id']
    assert data['price']['kind']=='forecast' and data['price']['history']
    filtered=client.get('/api/v4/markets',params={'crop':'Onion','state':row['state'],'district':row['district'],'search':row['market'],'min_price':row['predicted_price'],'max_price':row['predicted_price'],'recent':True}).json()
    assert row['series_id'] in [r['series_id'] for r in filtered['rows']]
    assert client.get('/api/v4/market-intelligence',params={'crop':'Onion','series_id':'bad'}).status_code==404
    assert client.get('/api/v4/market-intelligence',params={'crop':'Onion','series_id':row['series_id'],'quantity':0}).status_code==422


def test_environment_endpoint_and_no_data_contract(monkeypatch):
    monkeypatch.setattr(m,'resolve',lambda *a:{'coordinate':None})
    response=TestClient(app).get('/api/v4/market-environment?crop=Onion&series_id=unmapped')
    assert response.status_code==200 and not response.json()['available']
    assert response.json()['batch_id']


def test_missing_history_keeps_other_market_context_available(monkeypatch):
    from fastapi import HTTPException
    row=s.markets('Onion')[0]
    def missing(*args):raise HTTPException(503,'Missing history artifact')
    monkeypatch.setattr(m.daily,'history',missing)
    data=m.detail('Onion',row['series_id'])
    assert data['price']['history']==[] and data['price']['trend_pct'] is None
    assert data['price']['history_note'] and data['decision']['headline']
