"""Weather forecast service and endpoints (D-57), with a mocked provider: validation, cache lifetime, stale fallback,
outage, no zero-filling, switch-off, route coverage wording and no official-warning claim. No network access."""

from datetime import datetime, timedelta, timezone

import pytest
import requests

from Code.weather import forecast as fc

T0 = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)


def body(rain=(0.1, 4.3, 70.0, None, 15.3, 1.2, 1.8), prob=(53, 96, 78, 76, 65, 65, 33), tmax=(31.2, 29.7, 30.2, 28.3, 28.1, 29.0, 30.0)):
    return {"daily_units": {"time": "iso8601", "precipitation_sum": "mm", "temperature_2m_max": "°C", "precipitation_probability_max": "%"},
            "daily": {"time": [f"2026-10-{29 + i}" if i < 3 else f"2026-11-0{i - 2}" for i in range(7)],
                      "precipitation_sum": list(rain), "temperature_2m_max": list(tmax), "precipitation_probability_max": list(prob)}}


def ok(lat, lon):
    return fc.parse(body())


def boom(lat, lon):
    raise requests.ConnectionError("down")


def test_parse_keeps_missing_values_missing_and_checks_units_and_ranges():
    days = fc.parse(body())
    assert len(days) == 7 and days[3]["rain_mm"] is None and days[2]["rain_mm"] == 70.0
    assert set(days[0]) == {"date", "rain_mm", "tmax_c", "rain_probability_pct"}
    bad_unit = body(); bad_unit["daily_units"]["precipitation_sum"] = "inch"
    for b, msg in [(bad_unit, "unit"), (body(rain=(-1, 0, 0, 0, 0, 0, 0)), "outside"), (body(prob=(150, 0, 0, 0, 0, 0, 0)), "outside"),
                   ({"daily": {"time": ["2026-10-29"]}}, "7-day"), (body(rain=(0,) * 6), "missing or not")]:
        with pytest.raises(fc.ForecastError, match=msg):
            fc.parse(b)


def test_cache_is_reused_within_its_lifetime_then_refreshed(tmp_path):
    calls = []
    def counting(lat, lon):
        calls.append((lat, lon)); return ok(lat, lon)
    a = fc.forecast("P", 20, 73, now=T0, cache=tmp_path, fetcher=counting)
    b = fc.forecast("P", 20, 73, now=T0 + timedelta(hours=2), cache=tmp_path, fetcher=counting)
    assert a["available"] and not a["stale"] and b["retrieved_utc"] == a["retrieved_utc"] and len(calls) == 1
    c = fc.forecast("P", 20, 73, now=T0 + fc.TTL + timedelta(minutes=1), cache=tmp_path, fetcher=counting)
    assert len(calls) == 2 and c["retrieved_utc"] > a["retrieved_utc"]
    assert not list(tmp_path.glob("*.tmp"))                             # atomic writes leave no partial files


def test_outage_serves_the_last_good_copy_as_stale_then_nothing(tmp_path):
    fc.forecast("P", 20, 73, now=T0, cache=tmp_path, fetcher=ok)
    s = fc.forecast("P", 20, 73, now=T0 + timedelta(hours=5), cache=tmp_path, fetcher=boom)
    assert s["available"] and s["stale"] and s["retrieved_utc"] == T0.isoformat(timespec="seconds") and "failed" in s["reason"]
    gone = fc.forecast("P", 20, 73, now=T0 + fc.KEEP + timedelta(hours=1), cache=tmp_path, fetcher=boom)
    assert gone == gone | {"available": False, "days": [], "retrieved_utc": None}


def test_no_copy_and_provider_down_is_unavailable_never_zeros(tmp_path):
    r = fc.forecast("Q", 20, 73, now=T0, cache=tmp_path, fetcher=boom)
    assert r["available"] is False and r["days"] == [] and r["official_warning"] is False
    def malformed(lat, lon):
        return fc.parse({"daily": {}})
    assert fc.forecast("Q", 20, 73, now=T0, cache=tmp_path, fetcher=malformed)["available"] is False


def test_switch_off_makes_no_request(tmp_path, monkeypatch):
    monkeypatch.setenv("BDA_WEATHER_FORECAST", "0")
    r = fc.forecast("P", 20, 73, now=T0, cache=tmp_path, fetcher=boom)
    assert r["available"] is False and "switched off" in r["reason"] and not list(tmp_path.iterdir())


def test_heavy_rain_flags_use_the_threshold_and_skip_missing_days():
    assert fc.flags(fc.parse(body())) == [{"date": "2026-10-31", "rain_mm": 70.0}]


# ---------------------------------------------------------------- endpoints, provider mocked
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from Code.api import main as api  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "CACHE", tmp_path)
    real = fc.forecast
    monkeypatch.setattr(fc, "forecast", lambda key, lat, lon: real(key, lat, lon, cache=tmp_path, fetcher=ok))
    return TestClient(api.app)


def test_location_forecast_endpoint(client):
    r = client.get("/api/locations/0/forecast").json()
    assert r["available"] and len(r["days"]) == 7 and r["attribution"]["licence"] == "CC BY 4.0"
    assert "approximate" in r["location_meaning"] and r["official_warning"] is False and r["heavy_rain_days"][0]["rain_mm"] == 70.0
    assert client.get("/api/locations/999/forecast").status_code == 404


def test_route_weather_covers_only_the_end_points_and_never_claims_closure(client):
    nodes = client.get("/api/routes/nodes").json()
    a, b = nodes[0]["node_id"], nodes[1]["node_id"]
    r = client.get("/api/routes/weather", params={"origin": a, "dest": b}).json()
    assert r["coverage"].startswith("start and end district points only") and r["official_warning"] is False
    assert r["origin"]["node_id"] == a and r["dest"]["node_id"] == b
    assert r["message"] == "Heavy rain is forecast near the start and end of this route. Check current road conditions before dispatch."
    assert not any(w in r["message"].lower() for w in ("closed", "unsafe", "blocked", "delay"))
    assert client.get("/api/routes/weather", params={"origin": "D:Nowhere|X", "dest": b}).status_code == 404


def test_capabilities_keep_forecasts_and_live_status_separate(client):
    caps = {c["capability"]: c for c in client.get("/api/capabilities").json()}
    assert caps["Historical market prices and arrivals"]["live"] is False
    assert caps["Official weather warnings"]["status"] == "missing_data"
    assert caps["Price forecasts"]["live"] is False and caps["Price forecasts"]["status"] == "historical_evaluation_only"
    assert client.get("/api/health").json()["live_data"] is False
