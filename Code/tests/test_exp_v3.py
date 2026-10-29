"""exp-v3-prices (D-58) on synthetic data: causal forecasts, identical rows, protected windows, selection rule, test
gates and the run-once final test. The real final test window is never read here."""

import json

import numpy as np
import pandas as pd
import pytest

from Code.candidates import exp_v3 as ev


def weekly_frame(start="2024-02-05", end="2027-05-03", markets=("S1|D|A", "S1|D|B", "S2|D|C", "S2|D|D", "S3|D|E"), seed=0):
    rng = np.random.default_rng(seed)
    weeks = pd.date_range(start, end, freq="7D")
    out = []
    for i, m in enumerate(markets):
        level = 1000 + 100 * i + np.cumsum(rng.normal(0, 20, len(weeks)))
        out.append(pd.DataFrame({"Commodity": "Onion", "canonical_id": m, "Variety": "Red", "week_start": weeks, "target_median": level}))
    return pd.concat(out, ignore_index=True)


def model_table(w):
    s = ev.SERIES
    base = w.rename(columns={"week_start": "origin_week_start", "target_median": "y_origin"})
    lag4 = w.assign(week_start=w.week_start + pd.Timedelta(weeks=4)).rename(columns={"week_start": "origin_week_start", "target_median": "lag4"})
    base = base.merge(lag4, on=s + ["origin_week_start"], how="left")
    parts = []
    for h in ev.HORIZONS:
        t = w.assign(origin_week_start=w.week_start - pd.Timedelta(weeks=h)).rename(columns={"target_median": "y_target"})[s + ["origin_week_start", "y_target"]]
        parts.append(base.merge(t, on=s + ["origin_week_start"]).assign(horizon_weeks=h, target_week_start=lambda x: x.origin_week_start + pd.Timedelta(weeks=h)))
    mt = pd.concat(parts, ignore_index=True)
    return mt.assign(eligible_d41=mt.origin_week_start >= pd.Timestamp("2025-02-03"), state=mt.canonical_id.str.split("|").str[0])


def test_forecasts_use_only_cells_up_to_the_origin():
    w = weekly_frame(end="2025-12-29")
    mt = model_table(w)
    a = ev.forecasts(mt, w).set_index(ev.SERIES + ["origin_week_start", "horizon_weeks"])
    future = w.copy()
    future.loc[future.week_start > pd.Timestamp("2025-06-02"), "target_median"] *= 3        # change only later cells
    b = ev.forecasts(model_table(future), future).set_index(ev.SERIES + ["origin_week_start", "horizon_weeks"])
    early = a.index.get_level_values("origin_week_start") <= pd.Timestamp("2025-06-02")
    for m in ev.METHODS:
        pd.testing.assert_series_equal(a.loc[early, m], b.loc[a.index[early], m])


def test_trailing_median_drift_and_ewma_definitions():
    w = pd.DataFrame({"Commodity": "Onion", "canonical_id": "S|D|A", "Variety": "R",
                      "week_start": pd.to_datetime(["2025-01-06", "2025-01-13", "2025-01-27", "2025-02-03", "2025-02-10"]),
                      "target_median": [100.0, 200.0, 400.0, 300.0, 500.0]})
    f = ev.origin_features(w).set_index("origin_week_start")
    assert f.loc["2025-02-03", "trailing_median_4w"] == 300.0          # weeks 01-13 .. 02-03 observed: 200, 400, 300 (01-20 missing)
    assert f.loc["2025-01-06", "ewma_a05"] == 100.0 and f.loc["2025-01-13", "ewma_a05"] == 150.0
    mt = pd.DataFrame({"Commodity": "Onion", "canonical_id": "S|D|A", "Variety": "R", "origin_week_start": pd.to_datetime(["2025-02-10", "2025-01-13"]),
                       "y_origin": [500.0, 200.0], "lag4": [200.0, np.nan], "horizon_weeks": [2, 1]})
    d = ev.forecasts(mt, w)
    assert list(d.drift_4w) == [500 + 2 * (500 - 200) / 4, 200.0]


def test_validation_rows_never_reach_the_consumed_window_or_the_test():
    mt = model_table(weekly_frame())
    v = ev.rows(mt, ev.VALIDATION)
    assert v.target_sunday.max() <= pd.Timestamp("2026-06-28") and v.eligible_d41.all()
    with pytest.raises(SystemExit, match="consumed"):
        ev.rows(mt, ("2026-01-04", "2026-07-12"))
    t = ev.rows(mt, ev.TEST)
    assert t.target_sunday.min() >= pd.Timestamp("2026-11-01") and t.target_sunday.max() <= pd.Timestamp("2027-04-25")


def test_selection_advances_only_with_a_bonferroni_interval_above_zero():
    s = pd.DataFrame([{"crop": "Onion", "horizon_weeks": 1, "method": m, "mae": mae, "skill": sk, "skill_bonferroni_low": lo}
                      for m, mae, sk, lo in [("persistence", 10, 0, None), ("trailing_median_4w", 9, .1, .02), ("ewma_a05", 9.5, .05, .01), ("drift_4w", 12, -.2, -.3)]]
                     + [{"crop": "Wheat", "horizon_weeks": 1, "method": m, "mae": mae, "skill": sk, "skill_bonferroni_low": lo}
                        for m, mae, sk, lo in [("persistence", 10, 0, None), ("trailing_median_4w", 9.9, .01, -.01), ("ewma_a05", 11, -.1, -.2), ("drift_4w", 12, -.2, -.3)]])
    sel = ev.select(s).set_index("crop")
    assert sel.loc["Onion", "method"] == "trailing_median_4w" and bool(sel.loc["Onion", "advances"])
    assert sel.loc["Wheat", "method"] == "trailing_median_4w" and not bool(sel.loc["Wheat", "advances"])


def test_protocol_is_fixed_before_scoring(tmp_path):
    p = tmp_path / "proto.json"
    ev.register(p)
    with pytest.raises(FileExistsError):
        ev.register(p)
    ev.check_protocol(p)
    j = json.loads(p.read_text()); j["validation_target_sundays"] = ["2025-01-05", "2026-06-28"]; p.write_text(json.dumps(j))
    with pytest.raises(SystemExit, match="pre-registration"):
        ev.check_protocol(p)


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "check_protocol", lambda path=None: "synthetic")
    w = weekly_frame()
    d = tmp_path / "ds"; d.mkdir()
    w.to_parquet(d / "weekly_faq_only.parquet")
    model_table(w).drop(columns="state").to_parquet(d / "model_table_faq_only.parquet")
    (d / "build_manifest.json").write_text(json.dumps({"weeks": ["2024-02-05", "2027-04-26"]}))
    pd.DataFrame({"reported_date": pd.to_datetime(["2027-04-24"]), "retrieved_utc": ["2027-05-10T00:00:00+00:00"]}).to_parquet(d / "records_onion.parquet")
    return d


def test_final_test_refuses_until_the_window_is_complete_and_settled(dataset, tmp_path):
    with pytest.raises(SystemExit, match="confirm"):
        ev.test("yes", dataset=dataset, out=tmp_path / "t")
    (dataset / "build_manifest.json").write_text(json.dumps({"weeks": ["2024-02-05", "2026-10-19"]}))
    with pytest.raises(SystemExit, match="needs every week"):
        ev.test("exp-v3", dataset=dataset, out=tmp_path / "t")
    (dataset / "build_manifest.json").write_text(json.dumps({"weeks": ["2024-02-05", "2027-04-26"]}))
    pd.DataFrame({"reported_date": pd.to_datetime(["2027-04-24"]), "retrieved_utc": ["2027-04-28T00:00:00+00:00"]}).to_parquet(dataset / "records_onion.parquet")
    with pytest.raises(SystemExit, match="late records"):
        ev.test("exp-v3", dataset=dataset, out=tmp_path / "t")
    assert not (tmp_path / "t").exists()                                   # refused before any lock


def test_validation_then_single_final_test_end_to_end(dataset, tmp_path):
    s, sel = ev.validate(dataset=dataset, out=tmp_path / "val", b=200)
    assert set(s.method) == set(ev.METHODS) and (s.groupby(["crop", "horizon_weeks"]).rows.nunique() == 1).all()   # identical rows
    man = json.loads((tmp_path / "val" / "run_manifest.json").read_text())
    assert man["target_sundays"][1] <= "2026-06-28" and man["latest_cell_read"] <= "2026-06-28"
    sel.assign(advances=True).to_csv(tmp_path / "sel.csv", index=False)  # force every cell through to exercise acceptance
    ts, acc = ev.test("exp-v3", dataset=dataset, out=tmp_path / "t", selection=tmp_path / "sel.csv", b=200)
    assert set(acc.columns) >= {"accepted", "market_bonferroni_low", "state_ci95_low", "leave_one_state_out_min"}
    assert (tmp_path / "t" / "RUN_LOCK.json").exists() and (tmp_path / "t" / "RUN_COMPLETED.json").exists()
    with pytest.raises(SystemExit, match="run once"):
        ev.test("exp-v3", dataset=dataset, out=tmp_path / "t", selection=tmp_path / "sel.csv", b=200)
