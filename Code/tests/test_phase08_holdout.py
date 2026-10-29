"""
Phase 8 §P holdout runner tests on synthetic data: freeze and protocol hash, confirmation, run-once lock, holdout-row
scope, refit cutoffs, no-weather configuration and identical-row pairing. Real outputs are only read, never written.
"""

import json

import pandas as pd
import pytest

from Code.integration.pipeline import file_sha256
from Code.modelling import dataset as m
from Code.modelling import holdout_evaluation as he
from Code.tests.test_phase08_models import seasonal


def test_freeze_is_written_once_and_detects_changed_code_and_protocol(tmp_path):
    f, doc = tmp_path / "code.py", tmp_path / "plan.md"
    f.write_text("x = 1\n")
    doc.write_text("## O. before\ntext\n## P. Holdout\nrule A\n")
    path = tmp_path / "freeze.csv"
    he.freeze(path, files=[f], doc=doc)
    he.verify_freeze(path)
    with pytest.raises(m.ModellingError, match="written once"):
        he.freeze(path, files=[f], doc=doc)
    doc.write_text("## O. before\nchanged elsewhere\n## P. Holdout\nrule A\n")
    he.verify_freeze(path)                                  # only the §P text is bound
    doc.write_text("## O. before\ntext\n## P. Holdout\nrule B\n")
    with pytest.raises(m.ModellingError, match="changed since the freeze"):
        he.verify_freeze(path)


def test_real_protocol_section_is_found_and_freeze_lists_the_frozen_phase8_code(tmp_path):
    assert len(he.protocol_sha256()) == 64
    fz = he.freeze(tmp_path / "f.csv")
    assert {str(p) for p in he.FROZEN_FILES} == set(fz.loc[fz["item"] == "file", "name"])
    sel = fz[fz["item"] == "selection"].set_index("name")["value"]
    assert sel["Onion h=1"] == "hgb_conservative (no_weather)" and sel["every crop x horizon"] == "persistence"


def test_last_complete_sunday():
    assert he.last_complete_sunday("2024-02-02") == pd.Timestamp("2024-01-28")
    assert he.last_complete_sunday("2024-02-01") == pd.Timestamp("2024-01-28")
    assert he.last_complete_sunday("2024-01-28") == pd.Timestamp("2024-01-28")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("holdout")
    df = pd.concat([seasonal(days=2950), seasonal(level=2000.0, market="N", days=2950, review_every=50)], ignore_index=True)
    df["source_row"] = range(len(df))                 # 2016-01-04 .. 2024-02: train, validation, test and holdout
    (tmp / "f").mkdir()
    path = tmp / "f" / "features_onion.parquet"
    df.to_parquet(path, index=False)
    he.freeze(tmp / "freeze.csv")
    kw = dict(feature_dir=tmp / "f", out_dir=tmp / "out", crops=["Onion"], expected={str(path): file_sha256(path)},
              freeze_path=tmp / "freeze.csv", b_reps=200, expected_last=None)
    with pytest.raises(m.ModellingError, match="confirm='P'"):
        he.run_holdout_evaluation("yes", **kw)
    assert not (tmp / "out").exists()                 # refused before any lock or output
    out = he.run_holdout_evaluation("P", **kw)
    return tmp, kw, out, df


def test_only_eligible_holdout_rows_are_scored(run):
    _, _, out, df = run
    p = out["predictions"]
    end = he.last_complete_sunday(df["reported_date"].max())
    assert set(p["period"]) == {"holdout_2023", "holdout_2024_01"}
    assert p["target_sunday"].min() >= pd.Timestamp("2023-01-01") and p["target_sunday"].max() <= end
    r = out["holdout_results"].set_index(["approach", "horizon_weeks", "period"])
    for (a, h), g in out["holdout_results"].groupby(["approach", "horizon_weeks"]):
        assert r.loc[(a, h, he.COMBINED), "n_obs"] == r.loc[(a, h, "holdout_2023"), "n_obs"] + r.loc[(a, h, "holdout_2024_01"), "n_obs"]


def test_persistence_everywhere_and_learned_cell_on_identical_rows(run):
    _, _, out, _ = run
    r = out["holdout_results"]
    pers = r[r["approach"] == "persistence"]
    assert set(pers["horizon_weeks"]) == {1, 2, 4} and (pers["mae"] == pers["persistence_mae"]).all()
    learned = r[r["approach"] == "hgb_conservative"]
    assert set(learned["horizon_weeks"]) == {1} and set(learned["config"]) == {"no_weather"}
    p = out["predictions"]
    one = p[p["horizon_weeks"] == 1]
    assert sorted(one[one["model"] == "persistence"]["row"]) == sorted(one[one["model"] != "persistence"]["row"])
    bs = out["holdout_bootstrap"].query("cluster == 'series'").set_index("period")
    assert bs.loc[he.COMBINED, "n_obs"] == learned.set_index("period").loc[he.COMBINED, "n_obs"]


def test_every_refit_precedes_its_origins_and_uses_only_finished_targets(run):
    _, _, out, _ = run
    lg = out["holdout_refit_log"]
    assert len(lg) and (pd.to_datetime(lg["train_last_target_sunday"]) <= pd.to_datetime(lg["refit_date"])).all()
    p = out["predictions"].query("model != 'persistence'")
    refit = m.refit_date_for(pd.to_datetime(p["origin_date"]), m.refit_schedule())
    assert (refit <= pd.to_datetime(p["origin_date"])).all()


def test_second_run_is_refused_and_completion_matches_outputs(run):
    tmp, kw, _, _ = run
    done = json.loads((tmp / "out" / "RUN_COMPLETED.json").read_text())
    for name, sha in done["outputs_sha256"].items():
        assert file_sha256(tmp / "out" / name) == sha
    with pytest.raises(m.ModellingError, match="already been accessed"):
        he.run_holdout_evaluation("P", **kw)


def test_a_wrong_last_sunday_is_refused(tmp_path):
    ex = pd.DataFrame({"period": [], "eligible_at_origin": [], "target_sunday": [], "target_last_date": []})
    with pytest.raises(m.ModellingError, match="not the §P"):
        he.eval_rows(ex, "2024-03-01")


@pytest.mark.skipif(not he.DONE.exists(), reason="the §P holdout has not been run in this checkout")
def test_real_holdout_run_is_complete_frozen_and_unchanged():
    assert he.LOCK.exists()
    he.verify_freeze()
    done = json.loads(he.DONE.read_text())
    for name, sha in done["outputs_sha256"].items():
        assert file_sha256(he.OUT / name) == sha
    r = pd.read_csv(he.OUT / he.RESULTS_NAME)
    assert set(r["period"]) == {"holdout_2023", "holdout_2024_01", he.COMBINED}
    assert r["last_target_sunday"].max() == "2024-01-28" and r["first_target_sunday"].min() == "2023-01-01"
    with pytest.raises(m.ModellingError, match="already been accessed"):
        he._take_lock(he.OUT, "x")
