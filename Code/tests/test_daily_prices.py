"""Synthetic daily-extension checks. Never run or score frozen experiments."""
from datetime import datetime
import json
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from Code.daily import dataset as ds, operational as op
from Code.daily.policy import commodity, text, series_id, eligibility, IST, VERSION
from Code.daily.forecast import features, baselines, fit_models, learned_predictions
from Code.daily.evaluate import simulation_rows
from Code.api import daily as api
from Code.api.main import app

def history(end="2026-11-10", n=500):
    dates = pd.date_range(end=end, periods=n)
    return pd.DataFrame({"date": dates, "price": 1000 + np.arange(n, dtype=float),
                         "available_at": (dates + pd.Timedelta(days=1)).tz_localize(IST).astype(str),
                         "source_row": np.arange(n), "availability_basis": "synthetic", "series_id": "sid", "state": "State"})

def metadata():
    return {"crop": "TestCrop", "category": "Vegetables", "state": "State", "district": "District", "market": "Market",
            "variety": "Other", "series_id": "sid", "source": "agmarknet_archive", "grade": "unspecified"}

def test_aliases_do_not_merge_different_commodities_or_varieties():
    assert commodity(" soybean ") == "Soyabean"
    assert commodity("paddy") != commodity("Rice")
    assert commodity("moong") != commodity("Green Gram Dal (Moong Dal)")
    assert text("  Local   Red  ") == "Local Red"
    assert series_id("Onion", "archive", ["S", "D", "M", "Other"]) != series_id("Onion", "archive", ["S", "D", "M", "Local"])
    assert series_id("Onion", "archive", ["S", "D", "M", "Other"]) != series_id("Onion", "datagov", ["S", "D", "M", "Other"])

@pytest.mark.parametrize("n,end,status", [(100,"2026-11-10","insufficient_history"), (500,"2026-11-10","prediction_available"),
                         (500,"2026-11-06","stale_prediction"), (500,"2026-11-03","stale_unavailable")])
def test_daily_eligibility(n, end, status):
    h = history(end,n)
    assert eligibility(h.date, "2026-11-11")["status"] == status

def test_fragmented_history_is_not_eligible_and_absent_days_are_not_zero():
    dates = pd.date_range("2023-01-01", "2026-11-10", freq="5D")
    assert eligibility(dates, "2026-11-11")["status"] == "insufficient_history"
    h = history().iloc[::2]
    x, e, known = features(h, "2026-11-11", "2026-11-11T09:00:00+05:30")
    assert len(known) == len(h)
    assert baselines(known, "2026-11-11")["persistence"] == h.price.iloc[-1]

def test_future_reports_retrievals_and_today_are_excluded():
    h = history()
    x, e, known = features(h, "2026-11-11", "2026-11-11T09:00:00+05:30")
    extra = pd.DataFrame({"date": pd.to_datetime(["2026-11-11", "2026-11-12", "2026-11-09"]),
                          "price": [90000.,80000.,70000.], "available_at": ["2026-11-11T08:00:00+05:30", "2026-11-11T08:00:00+05:30", "2026-11-12T00:00:00+05:30"]})
    x2, _, k2 = features(pd.concat([h,extra], ignore_index=True), "2026-11-11", "2026-11-11T09:00:00+05:30")
    np.testing.assert_array_equal(x,x2)
    assert len(k2) == len(known)
    p = op.forecast_one(pd.concat([h, extra.iloc[:1]], ignore_index=True), metadata(), "2026-11-11T09:00:00+05:30", VERSION)
    assert p["observed_today"] == 90000
    assert p["predicted_modal_price"] == h.price.iloc[-1]

def test_ist_date_and_naive_timestamp_rejection():
    p = op.forecast_one(history(), metadata(), "2026-11-10T20:00:00Z", VERSION)
    assert p["target_date"] == "2026-11-11"
    with pytest.raises(ValueError, match="timezone"):
        features(history(), "2026-11-11", "2026-11-11T09:00:00")


def test_grouped_batch_matches_scalar_forecasts_with_reporting_and_availability_gaps():
    frames, identities = [], []
    for i,(n,end,step) in enumerate([(500,"2026-11-10",1),(500,"2026-11-06",1),
                                    (500,"2026-10-01",1),(80,"2026-11-10",1),
                                    (1500,"2026-11-10",5),(500,"2026-11-11",1)]):
        sid=f"sid{i}"
        h=history(end,n).iloc[::step].copy().assign(series_id=sid)
        if i==5:
            h["available_at"]=h.date.dt.tz_localize(IST).astype(str)
            h.loc[h.index[-2],"available_at"]="2026-11-12T09:00:00+05:30"
        frames.append(h)
        identities.append({**metadata(),"series_id":sid})
    # Includes a series whose entire history was unavailable at issue time.
    frames.append(history().assign(series_id="unavailable",available_at="2026-11-12T09:00:00+05:30"))
    identities.append({**metadata(),"series_id":"unavailable"})
    h=pd.concat(frames,ignore_index=True).sample(frac=1,random_state=4)
    registry=pd.DataFrame(identities).set_index("series_id")
    issue="2026-11-10T20:00:00Z"
    actual=op.forecast_source(h,registry,issue,VERSION)
    expected=[op.forecast_one(g,{"series_id":sid,**registry.loc[sid].to_dict()},issue,VERSION)
              for sid,g in h.groupby("series_id",sort=True)]
    assert actual==expected
    assert actual[-1]["status"]=="insufficient_history"


def test_grouped_batch_rejects_ambiguous_known_daily_keys():
    h=history()
    h=pd.concat([h,h.tail(1)],ignore_index=True)
    registry=pd.DataFrame([metadata()]).set_index("series_id")
    with pytest.raises(ValueError,match="Ambiguous"):
        op.forecast_source(h,registry,"2026-11-11T09:00:00+05:30",VERSION)

def test_baselines_and_learned_training_inference_are_deterministic():
    h = history()
    x, _, known = features(h, "2026-11-11", "2026-11-11T09:00:00+05:30")
    b = baselines(known,"2026-11-11")
    assert b["persistence"] == 1499
    assert b["seasonal_naive_7d"] == h.loc[h.date == "2026-11-04", "price"].iloc[0]
    assert b["moving_average_7obs"] == 1496
    train = np.tile(x,(80,1)) + np.random.default_rng(1).normal(0,.01,(80,len(x)))
    models = fit_models(train,np.zeros(80))
    result = learned_predictions(models,x.reshape(1,-1),[1499.])
    assert set(result) == {"ridge","hist_gradient_boosting"}
    for v in result.values():
        assert v[0] == pytest.approx(1499.)

def test_vectorized_simulation_matches_time_safe_features():
    g = history("2018-12-31",1500).iloc[::2].copy()
    g["available_at"] = (g.date + pd.Timedelta(days=3)).dt.tz_localize(IST).astype(str)
    examples, coverage = simulation_rows(g)
    assert examples and coverage["no_report"] > 0
    for row in examples[::11]:
        x, e, known = features(g,row["date"],pd.Timestamp(row["date"]).tz_localize(IST))
        np.testing.assert_allclose(x,row["x"],atol=1e-12)
        assert row["age_days"] == e["age_days"]
        assert row["persistence"] == baselines(known,row["date"])["persistence"]

def test_quality_rules_conflicts_zero_range_and_duplicates():
    from Code.integration.pipeline import MANDI_COLUMNS
    raw = pd.DataFrame({"State Name": ["S"]*6,"District Name":["D"]*6,"Market Name":["M"]*6,
                        "Variety":["V"]*6,"Group":["Vegetables"]*6,"Arrivals (Tonnes)":[1.]*6,
                        "Min Price (Rs./Quintal)":[100.]*6,"Max Price (Rs./Quintal)":[200.]*6,
                        "Modal Price (Rs./Quintal)":[150.,150.,0.,500.,140.,160.],
                        "Reported Date":pd.to_datetime(["2020-01-01","2020-01-01","2020-01-02","2020-01-03","2020-01-04","2020-01-04"])})
    raw = raw.rename(columns=MANDI_COLUMNS).assign(source_row=np.arange(6),crop="Onion")
    good, counts = ds.clean_prices(raw)
    assert len(good)==1 and counts["duplicate_records"]==1 and counts["conflicting_records"]==2

@pytest.fixture
def built(tmp_path,monkeypatch):
    monkeypatch.setattr(op,"OUT",tmp_path)
    monkeypatch.setattr(api,"OUT",tmp_path)
    monkeypatch.setattr(api,"now_ist",lambda: datetime(2026,11,11,9,tzinfo=IST))
    monkeypatch.setattr(op,"now_ist",lambda: datetime(2026,11,11,9,tzinfo=IST))
    storage=tmp_path/"archive/test"
    storage.mkdir(parents=True)
    h=history()
    meta=metadata()
    for key,value in meta.items():
        if key not in h:
            h[key]=value
    h.to_parquet(storage/"observations.parquet",index=False)
    s=ds.summarize_series(h,pd.Timestamp("2026-11-11"))
    s.to_parquet(storage/"series.parquet",index=False)
    catalog={"version":VERSION,"crops":[{"crop":"TestCrop","category":"Vegetables","storage":"archive/test", "source_path":"synthetic",
               "source_sha256":"synthetic","observations_sha256":ds.sha(storage/"observations.parquet")} ]}
    ds.write_json(tmp_path/"catalog.json",catalog)
    dest,_=op.release()
    op.batch("2026-11-11T09:00:00+05:30")
    api._snapshot.cache_clear()
    api._history.cache_clear()
    yield TestClient(app),dest
    api._snapshot.cache_clear()
    api._history.cache_clear()

def test_release_batch_api_contract_and_history(built):
    c,_=built
    assert c.get("/api/v3/daily/categories").json()==["Vegetables"]
    assert c.get("/api/v3/daily/crops").json()["crops"][0]["crop"]=="TestCrop"
    assert c.get("/api/v3/daily/locations",params={"crop":"TestCrop"}).json()==[{"state":"State","district":"District"}]
    assert c.get("/api/v3/daily/markets",params={"crop":"TestCrop","state":"State","district":"District"}).json()[0]["series_id"]=="sid"
    p=c.get("/api/v3/daily/today",params={"series_id":"sid"})
    assert p.status_code==200,p.text
    assert p.json()["kind"]=="prediction" and p.json()["predicted_modal_price"]==1499
    h=c.get("/api/v3/daily/history",params={"series_id":"sid","limit":5})
    assert h.status_code==200,h.text
    assert len(h.json()["points"])==5
    assert c.get("/api/v3/daily/history",params={"series_id":"sid","limit":0}).status_code==422
    assert c.get("/api/v3/daily/metadata").json()["crops"]==1
    assert c.get("/api/v3/daily/freshness").json()["eligible_predictions"]==1

def test_unsupported_locations_and_series(built):
    c,_=built
    for path,params in [("locations",{"crop":"Cotton"}),("locations",{"crop":"TestCrop","state":"Atlantis"}),
                        ("markets",{"crop":"TestCrop","state":"State","district":"Atlantis"}),("today",{"series_id":"missing"})]:
        assert c.get("/api/v3/daily/"+path,params=params).status_code==404

def test_expired_batch_never_served_as_today(built,monkeypatch):
    c,_=built
    monkeypatch.setattr(api,"now_ist",lambda: datetime(2026,11,12,9,tzinfo=IST))
    p=c.get("/api/v3/daily/today",params={"series_id":"sid"}).json()
    assert p["status"]=="batch_expired" and p["predicted_modal_price"] is None and p["target_date"]=="2026-11-12"

def test_artifact_tampering_is_rejected(built):
    c,dest=built
    assert c.get("/api/v3/daily/metadata").status_code==200  # populate the cache first
    (dest/"model.json").write_text('{"model":"something_else"}')
    assert c.get("/api/v3/daily/metadata").status_code==503


def test_missing_observation_artifact_is_service_unavailable(built):
    c,dest=built
    (dest.parents[1]/"archive/test/observations.parquet").unlink()
    response=c.get("/api/v3/daily/history",params={"series_id":"sid"})
    assert response.status_code==503
    assert "unavailable" in response.json()["detail"]

def test_missing_artifacts_are_unavailable(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"OUT",tmp_path)
    assert TestClient(app).get("/api/v3/daily/crops").status_code==503

def test_operational_issue_cannot_predate_dataset_model_release(built):
    with pytest.raises(ValueError,match="backdate"):
        op.batch("2026-11-11T08:59:59+05:30")

def test_crop_categories_keep_legacy_and_distinct_pulses():
    assert ds.CROP_CATEGORY["Onion"]=="Vegetables"
    assert ds.CROP_CATEGORY["Potato"]=="Vegetables"
    assert ds.CROP_CATEGORY["Wheat"]=="Cereals and grains"
    assert ds.CROP_CATEGORY["Bengal Gram(Gram)(Whole)"]=="Pulses and legumes"
