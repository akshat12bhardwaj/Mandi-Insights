"""Operational revamp: independent of protected model evaluation artifacts."""
import math
import pytest
from fastapi.testclient import TestClient
from Code.api.main import app
from Code.intelligence import service as s


def pair():
    common={'crop':'Onion','variety':'Other','grade':'FAQ','source':'datagov','predicted_price':1000,'state':'Haryana','district':'Ambala','market':'Buy','series_id':'buy','coordinate':s.coordinate('Haryana','Ambala')}
    sell={**common,'series_id':'sell','market':'Sell','predicted_price':1500,'state':'Punjab','district':'Ludhiana','coordinate':s.coordinate('Punjab','Ludhiana')}
    return common,sell


def test_dynamic_catalog_has_no_twenty_crop_cap():
    c=s.catalog()
    assert len(c['crops'])>=20
    assert {'Onion','Potato','Wheat'}<={r['crop'] for r in c['crops']}
    assert 'No crop-count cap' in c['selection_rule']
    assert len({r['crop'] for r in c['crops']})==len(c['crops'])


def test_capacity_is_deterministic_and_bounded():
    row={'warehouse_id':'test:1','name':'Test','facility_type':'warehouse','latitude':20.,'longitude':78.,'capacity_total_t':None}
    a=s.simulated_facility(row,'2026-11-12')
    assert a==s.simulated_facility(row,'2026-11-12')
    assert 0<a['occupied_t']<a['total_t']
    assert a['free_t']==round(a['total_t']-a['occupied_t'],2)
    assert 30<=a['occupancy_pct']<=95
    assert a['storage_class'] in s.CONFIG['storage']


def test_every_existing_warehouse_has_distinct_identity_and_nonempty_occupancy():
    facilities=s.warehouses()
    assert len(facilities)==len({r['warehouse_id'] for r in facilities})
    assert len({r['occupancy_pct'] for r in facilities})>=5
    assert all(0<r['free_t']<r['total_t'] for r in facilities)


def test_costs_multi_trip_and_loss_are_consistent():
    buy,sell=pair()
    r=s.calculate(buy,sell,101,'Medium truck',18,1)
    assert r['trips']==2
    assert r['transport']==round(r['route']['km']*35*2,2)
    assert r['total_cost']==round(101000+r['transport']+1818,2)
    assert r['sale_revenue']==round(1500*101*.99,2)
    assert r['margin']==round(r['sale_revenue']-r['total_cost'],2)
    assert r['storage']==0


def test_configurable_freight_and_payload():
    buy,sell=pair()
    r=s.calculate(buy,sell,100,'Medium truck',18,1,rs_km=40,capacity_q=30)
    assert r['trips']==4
    assert r['transport']==round(r['route']['km']*40*4,2)


def test_invalid_reported_capacity_uses_positive_simulation():
    row={'warehouse_id':'test:bad','name':'Test','facility_type':'warehouse','latitude':20.,'longitude':78.,'capacity_total_t':-50}
    w=s.simulated_facility(row,'2026-11-12')
    assert w['total_t']>0 and w['free_t']>0
    assert w['capacity_basis']=='Simulated capacity'


def test_storage_rejects_capacity_and_compatibility():
    buy,sell=pair()
    wh={'supported_crops':['Wheat'],'free_t':100,'max_days':30,'rs_q_day':1,'latitude':28,'longitude':77}
    with pytest.raises(ValueError): s.calculate(buy,sell,100,'Medium truck',18,1,7,wh)
    wh['supported_crops']=['Onion'];wh['free_t']=9
    with pytest.raises(ValueError): s.calculate(buy,sell,100,'Medium truck',18,1,7,wh)
    wh['free_t']=100
    r=s.calculate(buy,sell,100,'Medium truck',18,1,7,wh,future_change=10)
    assert r['storage']==700
    assert r['sale_price']==1650
    assert 'not a future forecast' in r['sale_basis']
    assert 'Approximate' in r['route']['basis']


def test_incompatible_market_prices_are_not_compared():
    buy,sell=pair();sell['variety']='Different'
    with pytest.raises(ValueError): s.calculate(buy,sell,100,'Medium truck',18,1)


def test_missing_mapping_does_not_invent_location():
    assert s.coordinate('Unmapped','Unknown') is None


def test_expired_batch_does_not_create_strategies(monkeypatch):
    monkeypatch.setattr(s,'current_prices',lambda:[])
    assert s.strategies()==([],0)


def test_api_validation_and_current_ranking():
    client=TestClient(app)
    assert client.get('/api/v4/overview').status_code==200
    assert client.get('/api/v4/strategies?quantity=-1').status_code==422
    assert client.get('/api/v4/strategies?vehicle=Unknown').status_code==422
    assert client.get('/api/v4/markets?crop=Fake').status_code==422
    assert client.post('/api/v4/scenario',json={'buy_id':'missing','sell_id':'missing'}).status_code==422
    result=client.get('/api/v4/strategies').json()
    assert len(result['rows'])<=24
    for r in result['rows']:
        assert math.isclose(r['margin'],r['sale_revenue']-r['total_cost'],abs_tol=.02)
        assert r['buy']['series_id']!=r['sell']['series_id']
        assert r['trips']>0
        assert r['buy']['source']==r['sell']['source']


def test_current_strategies_are_reproducible():
    a,n=s.strategies(quantity=100)
    b,m=s.strategies(quantity=100)
    assert a==b and n==m
