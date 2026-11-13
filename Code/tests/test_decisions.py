"""Synthetic decision scenarios. No protected record or evaluation is opened."""
from datetime import datetime
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from Code.api.main import app
from Code.api import decisions as api
from Code.decision import service as svc
from Code.decision.contracts import DecisionRequest,Transport
from Code.decision.costs import transport_cost,storage_cost
from Code.decision.weather import observed_features,variant_vectors
from Code.daily.forecast import FEATURES
from Code.daily.policy import IST


def price(sid="a",market="Market A",district="District A",value=2000.,grade="FAQ"):
    return {"series_id":sid,"crop":"Onion","state":"State","district":district,"market":market,"variety":"Red",
            "grade":grade,"source":"datagov","predicted_modal_price":value,"status":"prediction_available",
            "target_date":"2026-11-12","data_freshness":{"age_days":1}}


@pytest.fixture
def setup(monkeypatch):
    prices=[price(),price("b","Market B","District B",2100.),price("different","Other grade","District B",100.,"Grade B")]
    monkeypatch.setattr(svc.daily,"today",lambda sid:next(p.copy() for p in prices if p["series_id"]==sid))
    monkeypatch.setattr(svc.daily,"crop_rows",lambda crop:pd.DataFrame())
    monkeypatch.setattr(svc,"eligible_prices",lambda crop:prices)
    monkeypatch.setattr(svc,"now_ist",lambda:datetime(2026,11,12,9,tzinfo=IST))
    nodes=pd.DataFrame([{"node_id":nid,"state":"State","district":district,"verification":"passed","name":district,"latitude":20.,"longitude":75.}
                        for nid,district in [("A","District A"),("B","District B"),("DEST","Destination")]])
    monkeypatch.setattr(svc.lg,"routing_nodes",lambda:nodes)
    matrix=pd.DataFrame([{"origin_id":nid,"dest_id":"DEST","objective":objective,"status":"ok","road_distance_km":km,"travel_time_h":hours}
                          for nid,km in [("A",100.),("B",10.)] for objective,hours in [("shortest",3.),("fastest",2.)]])
    monkeypatch.setattr(svc.lg,"od",lambda:matrix)
    monkeypatch.setattr(svc.lg,"warehouses",lambda:pd.DataFrame([{"warehouse_id":"W","name":"Reported cold storage","facility_type":"cold_storage","latitude":20.,"longitude":75.,"suitability_status":"unknown","capacity_status":"unknown","charges_status":"unknown"}]))
    monkeypatch.setattr(svc.lg,"node_warehouse",lambda:pd.DataFrame([{"node_id":"A","warehouse_id":"W","road_distance_km":5.,"travel_time_h":.2}]))
    return TestClient(app),prices


def request(**kwargs):
    return DecisionRequest(series_id="a",quantity_quintals=10,destination="DEST",transport=Transport(
        freight_rs_per_tonne_km=20,destination_access_km=0,market_access_km={"a":0,"b":0}),**kwargs)


def test_quantity_units_freight_fuel_and_storage():
    assert transport_cost(100,10,Transport(freight_rs_per_tonne_km=20,fixed_trip_rs=100))==(2100.,None)
    # Inclusive freight and fuel are alternative calculations, never added together.
    assert transport_cost(100,10,Transport(mode="fuel",fuel_rs_per_litre=100,vehicle_km_per_litre=5,freight_rs_per_tonne_km=1000))==(2000.,2000.)
    assert transport_cost(100,10,Transport())==(None,None)
    assert storage_cost(20,15,300)==300.
    assert storage_cost(20,15,None) is None


def test_landed_cost_can_reverse_price_order_without_mixing_grades(setup):
    result=svc.compare(request())
    assert result["status"]=="scenario_comparison"
    assert result["cheapest_scenario_series_id"]=="b"
    assert result["markets"][0]["landed_cost"]==21200.
    assert result["markets"][1]["landed_cost"]==22000.
    assert {m["grade"] for m in result["markets"]}=={"FAQ"}
    assert result.get("potential_net_margin") is None
    assert "costed comparable" in result["summary"]


def test_missing_destination_or_access_prevents_landed_cost(setup):
    for payload in [DecisionRequest(series_id="a"),DecisionRequest(series_id="a",destination="DEST",transport=Transport(freight_rs_per_tonne_km=20))]:
        result=svc.compare(payload)
        assert result["cheapest_scenario_series_id"] is None
        assert all(m["landed_cost"] is None for m in result["markets"])


def test_storage_is_candidate_not_suitable_or_available(setup):
    payload=request(storage_rs_per_tonne_month=300,storage_days=15)
    payload.transport.warehouse_access_km={"W":1}
    result=api.compare(payload).model_dump() if hasattr(api.compare(payload),"model_dump") else api.compare(payload)
    candidate=result["storage"][0]
    assert candidate["storage_cost"]==150.
    assert candidate["transport_cost"]==120.
    assert candidate["scenario_total"]==20270.
    # HTTP validation inserts explicit unknowns, never warehouse-label inferences.
    response=setup[0].post('/api/v3/decisions/compare',json=payload.model_dump())
    assert response.status_code==200,response.text
    candidate=response.json()["storage"][0]
    assert candidate["available_capacity_t"] is None and candidate["suitability"]=="unknown"
    assert candidate["recommendation"]=="candidate_only"
    assert response.json()["future_revenue"] is None


def test_unavailable_forecast_offers_alternatives_without_storage_total(setup,monkeypatch):
    unavailable={**price(),"predicted_modal_price":None,"status":"stale_unavailable"}
    monkeypatch.setattr(svc.daily,"today",lambda sid:unavailable)
    monkeypatch.setattr(svc,"eligible_prices",lambda crop:[price("b","Market B","District B",2100.,"Grade B")])
    result=svc.compare(request(storage_rs_per_tonne_month=300))
    assert result["selected"] is None and result["cheapest_scenario_series_id"] is None
    assert "Switch" in result["summary"]
    assert result["storage"][0]["scenario_total"] is None


def test_no_current_crop_forecasts_is_unavailable(setup,monkeypatch):
    monkeypatch.setattr(svc,"eligible_prices",lambda crop:[])
    result=svc.compare(DecisionRequest(series_id="a"))
    assert result["status"]=="unavailable" and result["markets"]==[]


def test_expired_or_future_issued_batches_cannot_enter_comparisons(monkeypatch):
    now=datetime(2026,11,12,9,tzinfo=IST)
    monkeypatch.setattr(svc,"now_ist",lambda:now)
    for pointer in [{"target_date":"2026-11-11","issue":"2026-11-11T09:00:00+05:30"},
                    {"target_date":"2026-11-12","issue":"2026-11-12T10:00:00+05:30"}]:
        monkeypatch.setattr(svc.daily,"snapshot",lambda:(None,None,None,pointer))
        assert svc.eligible_prices("Onion")==[]


def test_unroutable_markets_are_not_given_zero_transport_cost(setup,monkeypatch):
    monkeypatch.setattr(svc.lg,"od",lambda:None)
    result=svc.compare(request())
    assert all(m["landed_cost"] is None and m["routes"]==[] for m in result["markets"])
    assert result["cheapest_scenario_series_id"] is None


def test_fixed_handling_charges_and_single_costed_scenario_are_explicit(setup):
    payload=request()
    payload.transport.market_access_km={"a":0}
    payload.transport.fixed_trip_rs=100
    payload.transport.handling_rs_per_quintal=5
    result=svc.compare(payload)
    assert result["selected"]["landed_cost"]==22150.
    assert result["cheapest_scenario_series_id"] is None
    assert "Only one" in result["summary"]


def test_api_contract_and_invalid_scenarios(setup):
    c,_=setup
    assert c.get('/api/v3/decisions/options',params={"crop":"Onion"}).status_code==200
    response=c.post('/api/v3/decisions/compare',json=request().model_dump())
    assert response.status_code==200,response.text
    assert response.json()["version"]=="decision-scenarios-v1"
    assert response.json()["quantity_tonnes"]==1
    for changes in [{"quantity_quintals":0},{"quantity_quintals":-1},{"future_price":999},{"storage_days":0}]:
        assert c.post('/api/v3/decisions/compare',json={**request().model_dump(),**changes}).status_code==422
    assert c.post('/api/v3/decisions/compare',json={**request().model_dump(),"destination":"UNKNOWN"}).status_code==404
    payload=request().model_dump();payload['transport']['market_access_km']={'a':-1}
    assert c.post('/api/v3/decisions/compare',json=payload).status_code==422


def test_weather_without_vintages_and_future_retrievals_is_not_backdated():
    dates=pd.date_range('2026-11-05','2026-11-11')
    frame=pd.DataFrame({'date':dates,'rain_sum':1.,'temperature_2m_max':30.,'relative_humidity_2m_mean':70.})
    assert observed_features(frame,'2026-11-12','2026-11-12T09:00:00+05:30')[0] is None
    frame['available_at']=(dates+pd.Timedelta(days=1)).tz_localize(IST).astype(str)
    features,reason=observed_features(frame,'2026-11-12','2026-11-12T09:00:00+05:30')
    np.testing.assert_allclose(features,[7.,30.,70.]);assert reason is None
    frame.loc[6,'available_at']='2026-11-13T00:00:00+05:30'
    assert observed_features(frame,'2026-11-12','2026-11-12T09:00:00+05:30')[0] is None
    with pytest.raises(ValueError,match='timezone'):
        observed_features(frame,'2026-11-12','2026-11-12T09:00:00')


def test_weather_comparison_variants_require_available_inputs():
    x=np.ones(len(FEATURES))
    variants=variant_vectors(x)
    assert len(variants['A_price'])==len(x)-4
    assert variants['C_weather'] is None and variants['D_weather_arrivals'] is None
    variants=variant_vectors(x,np.array([7.,30.,70.]),np.array([100.]))
    assert len(variants['D_weather_arrivals'])==len(x)+4


def test_weather_context_never_changes_price_model(setup,monkeypatch):
    monkeypatch.setattr(api.wx,'context',lambda *args:{'available':True,'days':[],'retrieved_utc':'2026-11-12T09:30:00Z'})
    original=svc.daily.today
    monkeypatch.setattr(svc.daily,'today',lambda sid:{**original(sid),'forecast_issue_timestamp':'2026-11-12T09:00:00+05:30'})
    result=setup[0].get('/api/v3/decisions/weather',params={'series_id':'a'})
    assert result.status_code==200,result.text
    assert result.json()['used_in_price_model'] is False
    assert result.json()['daily_validation']=='not_available'
