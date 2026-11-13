import json
from datetime import datetime
import pandas as pd
import pytest
from Code.tests.test_decisions import setup,price  # shared synthetic fixture, never protected evaluations
from Code.decision import trading as tr
from Code.decision.contracts import DecisionRequest,Transport
from Code.decision.costs import transport_cost,trip_count
from Code.daily import update
from Code.daily.policy import IST


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(tr,"path_identity",lambda a,b,o:o)
    monkeypatch.setattr(tr.svc.daily,"error_information",lambda c:{"mae":100.})


def trading_request(**kwargs):
    return DecisionRequest(series_id='a',region='all',quantity_quintals=10,transport=Transport(
        load_capacity_quintals=10,freight_rs_per_tonne_km=20,destination_access_km=0,market_access_km={'a':0,'b':0}),**kwargs)


def install_pair_routes(monkeypatch):
    matrix=pd.DataFrame([{'origin_id':'A','dest_id':'B','objective':o,'status':'ok','road_distance_km':100.,'travel_time_h':h}
                         for o,h in [('shortest',3.),('fastest',2.)]])
    monkeypatch.setattr(tr.svc.lg,'od',lambda:matrix)


def test_multiple_trip_costs_do_not_double_count_freight_and_fuel():
    assumptions=Transport(load_capacity_quintals=10,freight_rs_per_tonne_km=20,fixed_trip_rs=100,toll_rs_per_trip=50)
    assert trip_count(25,assumptions)==3
    assert transport_cost(100,25,assumptions)==(5450.,None)
    assumptions.mode='fuel';assumptions.fuel_rs_per_litre=100;assumptions.vehicle_km_per_litre=5
    assert transport_cost(100,25,assumptions)==(6450.,6000.)
    assumptions.mode='per_km';assumptions.rs_per_vehicle_km=10
    assert transport_cost(100,25,assumptions)==(3450.,None)


def test_buying_ranking_uses_error_screen_instead_of_tiny_price_advantage(setup):
    result=tr.compare(trading_request(objective='buy_now'))
    assert result['plan']['ranking']=='similar_within_error_screen'
    assert 'no clear winner' in result['summary']
    assert result['uncertainty']['calibrated'] is False


def test_owned_produce_sale_proceeds_are_not_profit(setup,monkeypatch):
    install_pair_routes(monkeypatch)
    request=trading_request(objective='sell_now',preferred_sell_series_id='b')
    result=tr.compare(request)
    plan=result['plan']
    assert plan['procurement_cost'] is None and plan['estimated_margin'] is None
    assert 'not profit' in result['summary']
    assert plan['sale_revenue']==21000 and plan['net_sale_proceeds']==19000
    request.acquisition_rs_per_quintal=1500
    plan=tr.compare(request)['plan']
    assert plan['estimated_margin']==4000


def test_negative_sale_proceeds_are_not_displayed_as_positive(setup,monkeypatch):
    install_pair_routes(monkeypatch)
    request=trading_request(objective='sell_now',preferred_sell_series_id='b')
    request.transport.freight_rs_per_tonne_km=1000
    result=tr.compare(request)
    assert result['plan']['net_sale_proceeds']<0 and '₹-' in result['summary']


def test_trade_margin_needs_both_prices_and_all_trip_inputs(setup,monkeypatch):
    install_pair_routes(monkeypatch)
    request=trading_request(objective='buy_deliver',preferred_sell_series_id='b')
    result=tr.compare(request)
    trade=next(s for s in result['scenarios'] if s['kind']=='trade')
    assert trade['procurement_cost']==20000 and trade['total_cost']==22000 and trade['estimated_margin']==-1000
    request.transport.load_capacity_quintals=None
    result=tr.compare(request)
    assert all(s['estimated_margin'] is None and not s['complete'] for s in result['scenarios'])


def test_incompatible_grade_cannot_be_selected_as_a_sale(setup):
    with pytest.raises(Exception) as error:
        tr.compare(trading_request(objective='sell_now',preferred_sell_series_id='different'))
    assert error.value.status_code==422


def test_maximum_transport_limit_and_duplicate_path_collapse(setup,monkeypatch):
    request=trading_request(destination='DEST')
    monkeypatch.setattr(tr,'path_identity',lambda *args:'same_geometry')
    _,_,routes,_=tr.routes_between(price(),None,request)
    assert len(routes)==1 and routes[0]['objectives']==['shortest','fastest']
    request.max_transport_km=50
    _,_,routes,_=tr.routes_between(price(),None,request)
    assert routes==[]


def test_storage_does_not_gain_future_revenue_from_today_sale_prices(setup):
    result=tr.compare(trading_request(objective='buy_store_sell'))
    assert result['plan'] is None and result['future_revenue'] is None
    assert all(s['sale_revenue'] is None and not s['complete'] for s in result['scenarios'])


def test_typed_trading_api_preserves_scenario_provenance(setup):
    response=setup[0].post('/api/v3/decisions/trading',json=trading_request(objective='buy_now').model_dump())
    assert response.status_code==200,response.text
    body=response.json()
    assert body['version']=='trading-scenarios-v2'
    assert body['provenance']['price_unit']=='INR/quintal'
    assert body['assumptions']['transport']['load_capacity_quintals']==10


@pytest.fixture
def refresh_env(tmp_path,monkeypatch):
    monkeypatch.setattr(update,'OUT',tmp_path)
    monkeypatch.setattr(update,'now_ist',lambda:datetime(2026,11,12,10,tzinfo=IST))
    (tmp_path/'catalog.json').write_text(json.dumps({'crops':[{'crop':'Onion'}]}))
    dest=tmp_path/'releases/old';dest.mkdir(parents=True);(dest/'manifest.json').write_text('{}')
    release={'release':'old','manifest_sha256':update.sha(dest/'manifest.json')}
    batch={'target_date':'2026-11-12','path':'old.sqlite'}
    (tmp_path/'release.json').write_text(json.dumps(release));(tmp_path/'batch.json').write_text(json.dumps(batch))
    monkeypatch.setattr(update.op,'release',lambda publish=False:(dest,{}))
    return tmp_path,release,batch


def test_update_plan_is_offline_and_no_change_is_idempotent(refresh_env,monkeypatch):
    def forbidden(**kwargs):raise AssertionError('No batch should be regenerated')
    monkeypatch.setattr(update.op,'batch',forbidden)
    plan=update.run(execute=False)
    assert plan['scheduled_execution_active'] is False
    for _ in range(2):
        result=update.run(execute=True,collector=lambda *a:{'calls':0,'accepted_partitions':0})
        assert result['status']=='unchanged_current_batch'
    assert not (refresh_env[0]/'update.lock').exists()


def test_source_failure_retains_previous_pointers(refresh_env):
    root,release,batch=refresh_env
    def fail(*args):raise ValueError('provider failed')
    with pytest.raises(ValueError):update.run(execute=True,collector=fail)
    assert json.loads((root/'release.json').read_text())==release
    assert json.loads((root/'batch.json').read_text())==batch
    assert json.loads((root/'update_status.json').read_text())['status']=='failed_previous_release_retained'


def test_update_does_not_replace_release_during_batch_preparation(refresh_env,monkeypatch):
    root,release,batch=refresh_env
    new=root/'releases/new';new.mkdir();(new/'manifest.json').write_text('{"new":true}')
    monkeypatch.setattr(update.op,'release',lambda publish=False:(new,{}))
    def fail(**kwargs):
        assert json.loads((root/'release.json').read_text())==release
        raise ValueError('batch failed')
    monkeypatch.setattr(update.op,'batch',fail)
    with pytest.raises(ValueError):update.run(execute=True,collector=lambda *a:{'calls':0})
    assert json.loads((root/'release.json').read_text())==release
    assert json.loads((root/'batch.json').read_text())==batch
