"""/api/v2/markets/* (D-56): observed recent prices only, declared segments and breaks, honest 503 when not built,
and v1 endpoints unchanged by the new router."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from Code.api import main as api, v2
from Code.app import data_v2
from Code.candidates import recent_prices as rp

client = TestClient(api.app)
built = pytest.mark.skipif(not rp.TABLE.exists(), reason="recent price table not built")


def get(url, status=200, **params):
    r = client.get(url, params=params)
    assert r.status_code == status, (url, r.status_code, r.text[:300])
    return r.json()


@built
def test_meta_declares_sources_breaks_attribution_and_not_live():
    m = get("/api/v2/markets/meta")
    assert m["available"] and m["kind"] == "observed" and m["live"] is False
    assert [s["source"] for s in m["segments"]] == ["agmarknet_archive", "datagov"]
    assert [b["date"] for b in m["breaks"]] == ["2024-02-03", "2025-11-07"]
    assert "data.gov.in" in m["attribution"] and "Maharashtra" in m["states_by_crop"]["Onion"]
    assert "Keralam" not in m["states_by_crop"]["Onion"]


@built
def test_weekly_rows_are_observed_medians_inside_their_segments():
    rows = get("/api/v2/markets/weekly", crop="Onion", state="Maharashtra")
    assert rows and set(rows[0]) == {"week_start", "source", "records", "markets", "modal_price_median"}
    weeks = [r["week_start"] for r in rows]
    assert weeks == sorted(weeks) and len(set(weeks)) == len(weeks)
    arch = [r["week_start"] for r in rows if r["source"] == "agmarknet_archive"]
    new = [r["week_start"] for r in rows if r["source"] == "datagov"]
    assert arch[0] >= "2020-07-06" and arch[-1] < "2024-02-03" <= new[0]
    get("/api/v2/markets/weekly", 404, crop="Onion", state="Atlantis")
    get("/api/v2/markets/weekly", 422, crop="Rice", state="Maharashtra")


def test_not_built_gives_503_and_an_honest_meta(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "TABLE", tmp_path / "none.parquet")
    monkeypatch.setattr(rp, "DEST", tmp_path)
    v2.weekly.cache_clear()
    assert get("/api/v2/markets/meta") == {"available": False, "message": "Recent prices are not built in this checkout."}
    get("/api/v2/markets/weekly", 503, crop="Onion", state="Maharashtra")
    v2.weekly.cache_clear()


def test_loader_refuses_rows_outside_declared_segments(monkeypatch, tmp_path):
    import json
    import pandas as pd
    t = pd.DataFrame({"crop": ["Onion"], "state": ["X"], "week_start": pd.to_datetime(["2026-11-02"]), "source": ["datagov"],
                      "records": [1], "markets": [1], "modal_price_median": [10.0]})
    t.to_parquet(tmp_path / "w.parquet")
    (tmp_path / "reporting_manifest.json").write_text(json.dumps({"segments": {"datagov": ["2024-02-05", "2026-10-19"]}}))
    monkeypatch.setattr(rp, "TABLE", tmp_path / "w.parquet")
    monkeypatch.setattr(rp, "DEST", tmp_path)
    with pytest.raises(data_v2.BoundaryError, match="outside"):
        data_v2.weekly_state()


def test_v1_health_still_reports_no_live_data():
    h = get("/api/health")
    assert h["live_data"] is False and h["market_history_end"] == "2020-06-30"
