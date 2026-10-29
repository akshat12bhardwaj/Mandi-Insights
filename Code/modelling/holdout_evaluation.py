"""
Phase 8 §P — the single evaluation of the pre-specified 2023+ no-weather holdout (Phase_08_Modelling_Plan.md §P). Run once.

  approaches = persistence for every crop x horizon (the D-42 choice); Onion h=1 additionally hgb_conservative with the
               no_weather feature config and unchanged settings, reported as a comparison, never as a replacement
  rows       = primary-experiment examples eligible at their origin (D-41) whose target Sunday falls in
               2023-01-01 .. the last Sunday on or before the crop's last reported date (2024-01-28 with the current data)
  refits     = latest quarterly refit <= origin (2022-10-02 .. 2024-01-07), trained on training_examples(ex, refit),
               exactly the Phase 8 rule: every target that ended by the refit date, never a later one
  scoring    = MAE / RMSE / MAPE vs persistence on identical rows, for 2023, 2024-01 and combined; the §K/§N paired
               bootstrap (series and market clusters, 10,000 replicates, seed 20261022) for the learned cell
  guards     = freeze() hashes this module, the frozen Phase 8 code, the registry and the §P protocol text;
               run_holdout_evaluation() refuses unless the freeze verifies, the protected inputs match their Phase 7
               fingerprints, no lock / result exists, and it is called with confirm="P". RUN_LOCK.json is created
               exclusively before any holdout row is scored; any existing lock refuses every later run.
Nothing here changes D-42: the selection, the 2021-2022 test and every earlier output stay as recorded.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from Code.features.pipeline import FEATURE_DIR, SERIES
from Code.integration.pipeline import file_sha256
from Code.modelling import baselines as b
from Code.modelling import dataset as d
from Code.modelling import final_evaluation as fe
from Code.modelling import models as mo
from Code.modelling import uncertainty as u

log = logging.getLogger("phase8_holdout")
PERIOD = "holdout_no_weather"
APPROACHES = {("Onion", 1): ("hgb_conservative", "no_weather")}   # §P; all other crop x horizon cells: persistence
YEARS = {"holdout_2023": ("2023-01-01", "2023-12-31"), "holdout_2024_01": ("2024-01-01", "2024-01-31")}
COMBINED = "holdout_combined"
EXPECTED_LAST_SUNDAY = pd.Timestamp("2024-01-28")                  # §P "with the current data"
PROTOCOL_DOC = Path("Documentation/Phase_08_Modelling_Plan.md")
OUT = d.MODEL_DATA_DIR / "holdout_2023"
FREEZE, LOCK, DONE = OUT / "holdout_freeze_manifest.csv", OUT / "RUN_LOCK.json", OUT / "RUN_COMPLETED.json"
RESULTS_NAME = "holdout_results.csv"
FROZEN_FILES = fe.FROZEN_FILES + [Path("Code/modelling/holdout_evaluation.py")]


def protocol_sha256(doc: Path = PROTOCOL_DOC) -> str:
    """SHA-256 of the §P text (LF-normalised, from its heading to the next '## ' heading or the end of the file)."""
    import hashlib
    text = Path(doc).read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"^## P\. .*?(?=^## |\Z)", text, flags=re.S | re.M)
    if not m:
        raise d.ModellingError(f"§P not found in {doc}")
    return hashlib.sha256(m.group(0).encode("utf-8")).hexdigest()


def _selection_rows() -> list[dict]:
    rows = [{"item": "selection", "name": f"{c} h={h}", "value": f"{m} ({cfg})"} for (c, h), (m, cfg) in APPROACHES.items()]
    return rows + [{"item": "selection", "name": "every crop x horizon", "value": "persistence"}]


def freeze(path: Path = FREEZE, files=FROZEN_FILES, doc: Path = PROTOCOL_DOC) -> pd.DataFrame:
    if Path(path).exists():
        raise d.ModellingError(f"{path} already exists; the freeze is written once")
    rows = [{"item": "file", "name": str(f), "value": file_sha256(f)} for f in files]
    rows.append({"item": "protocol", "name": f"{doc} §P", "value": protocol_sha256(doc)})
    rows += _selection_rows()
    params = mo.LEARNERS["hgb_conservative"]().get_params()
    rows.append({"item": "settings", "name": "hgb_conservative", "value": "; ".join(f"{k}={params[k]}" for k in sorted(params))})
    out = pd.DataFrame(rows)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return out


def verify_freeze(path: Path = FREEZE) -> None:
    if not Path(path).exists():
        raise d.ModellingError("no holdout freeze manifest; run freeze() first")
    fz = pd.read_csv(path)
    changed = [n for n, v in fz.loc[fz["item"] == "file", ["name", "value"]].itertuples(index=False) if file_sha256(n) != v]
    for n, v in fz.loc[fz["item"] == "protocol", ["name", "value"]].itertuples(index=False):
        if protocol_sha256(Path(n.removesuffix(" §P"))) != v:
            changed.append(n)
    if changed:
        raise d.ModellingError(f"frozen files changed since the freeze: {changed}")
    want = {r.name: r.value for r in fz[fz["item"] == "selection"].itertuples()}
    if want != {r["name"]: r["value"] for r in _selection_rows()}:
        raise d.ModellingError("approaches differ from the frozen §P approaches")
    params = mo.LEARNERS["hgb_conservative"]().get_params()
    if fz.loc[fz["item"] == "settings", "value"].iloc[0] != "; ".join(f"{k}={params[k]}" for k in sorted(params)):
        raise d.ModellingError("hgb_conservative settings differ from the freeze")


def last_complete_sunday(last_date) -> pd.Timestamp:
    t = pd.Timestamp(last_date).normalize()
    return t - pd.Timedelta(days=(t.dayofweek + 1) % 7)


def eval_rows(ex: pd.DataFrame, last_date, expected_last: pd.Timestamp | None = EXPECTED_LAST_SUNDAY) -> pd.DataFrame:
    end = last_complete_sunday(last_date)
    if expected_last is not None and end != expected_last:
        raise d.ModellingError(f"last complete target Sunday is {end.date()}, not the §P {expected_last.date()}")
    ev = ex[(ex["period"] == PERIOD) & ex["eligible_at_origin"]]
    if (ev["target_sunday"] > end).any() or (ev["target_sunday"] < pd.Timestamp("2023-01-01")).any():
        raise d.ModellingError("a holdout row outside 2023-01-01 .. the last complete Sunday")
    if (ev["target_last_date"] > pd.Timestamp(last_date)).any():
        raise d.ModellingError("a target uses data after the crop's last reported date")
    year = pd.Series(pd.NA, index=ev.index, dtype=object)
    for name, (a, z) in YEARS.items():
        year[ev["target_sunday"].between(pd.Timestamp(a), pd.Timestamp(z))] = name
    if year.isna().any():
        raise d.ModellingError("holdout rows outside the reporting periods")
    return ev.assign(holdout_year=year)


def predict(ex, reg, crop, h, last_date, schedule=None, expected_last=EXPECTED_LAST_SUNDAY):
    ev = eval_rows(ex, last_date, expected_last)
    base = pd.DataFrame({"crop": crop, "horizon_weeks": h, "experiment": "primary", "row": ev.index,
                         **{c: ev[c].astype(str).to_numpy() for c in SERIES if c != "crop"},
                         "origin_date": ev["origin_date"].to_numpy(), "target_sunday": ev["target_sunday"].to_numpy(),
                         "period": ev["holdout_year"].to_numpy(), "y": ev[d.TARGET].to_numpy(),
                         "persistence": ev["origin_week_median"].to_numpy()}, index=ev.index)
    pers = base.assign(model="persistence", config="none", yhat=base["persistence"])
    approach = APPROACHES.get((crop, h))
    if approach is None:
        return pers, []
    model, config = approach
    cols = d.feature_columns(reg, config)
    if any(c.startswith("wx_") for c in cols):
        raise d.ModellingError("the holdout configuration contains a wx_* column")
    schedule = d.refit_schedule() if schedule is None else schedule
    refit = d.refit_date_for(ev["origin_date"], schedule)
    yhat, log_rows = pd.Series(index=ev.index, dtype=float), []
    for r in sorted(refit.unique()):
        tr = d.training_examples(ex, r)
        if tr.empty or tr["target_sunday"].max() > r or (tr["target_last_date"] > r).any():
            raise d.ModellingError(f"invalid training set at refit {r.date()}")
        idx = refit.index[refit == r]
        if (ev.loc[idx, "origin_date"] < r).any():
            raise d.ModellingError("refit after origin")
        t0 = time.time()
        yhat[idx] = mo.make_model(model, config, reg).fit(tr).predict(ev.loc[idx])
        log_rows.append({"crop": crop, "horizon_weeks": h, "model": model, "config": config,
                         "refit_date": r.date().isoformat(), "n_train": len(tr),
                         "n_train_holdout_targets": int(tr["period"].eq(PERIOD).sum()),
                         "train_last_target_sunday": tr["target_sunday"].max().date().isoformat(),
                         "n_holdout_rows": len(idx), "fit_seconds": round(time.time() - t0, 2)})
    return pd.concat([pers, base.assign(model=model, config=config, yhat=yhat)]), log_rows


def score(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (crop, h, model, config), g in p.groupby(["crop", "horizon_weeks", "model", "config"], sort=True):
        for period, part in [(y, g[g["period"] == y]) for y in YEARS] + [(COMBINED, g)]:
            if part.empty:
                continue
            m, pm = b.metrics(part["y"], part["yhat"]), b.metrics(part["y"], part["persistence"])
            rows.append({"crop": crop, "horizon_weeks": h, "approach": model, "config": config, "period": period,
                         "n_obs": m["n"], "n_series": part[["state", "district", "market", "variety"]].drop_duplicates().shape[0],
                         "n_markets": part[["state", "district", "market"]].drop_duplicates().shape[0],
                         "first_target_sunday": pd.Timestamp(part["target_sunday"].min()).date().isoformat(),
                         "last_target_sunday": pd.Timestamp(part["target_sunday"].max()).date().isoformat(),
                         "mae": m["mae"], "rmse": m["rmse"], "mape_pct": m["mape_pct"],
                         "persistence_mae": pm["mae"], "persistence_rmse": pm["rmse"], "persistence_mape_pct": pm["mape_pct"],
                         "mae_improvement": pm["mae"] - m["mae"], "rel_mae_improvement_pct": 100 * (1 - m["mae"] / pm["mae"])})
    return pd.DataFrame(rows)


def _take_lock(out: Path, freeze_sha: str) -> None:
    for f in (out / DONE.name, out / LOCK.name, out / RESULTS_NAME):
        if f.exists():
            raise d.ModellingError(f"{f} exists: the §P holdout has already been accessed; it is evaluated once. "
                                   "Do not delete the lock to rerun; recovery needs a new decision entry")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / LOCK.name, "x", encoding="utf-8") as fh:
        json.dump({"protocol": "Phase 8 §P", "status": "started; holdout rows are scored after this file exists",
                   "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "freeze_manifest_sha256": freeze_sha}, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())


def run_holdout_evaluation(confirm: str, feature_dir: Path = FEATURE_DIR, out_dir: Path = OUT, crops: list[str] | None = None,
                           expected: dict[str, str] | None = None, registry_path: Path = d.REGISTRY_PATH,
                           freeze_path: Path = FREEZE, b_reps: int = u.B, expected_last=EXPECTED_LAST_SUNDAY) -> dict:
    if confirm != "P":
        raise d.ModellingError("the single §P run needs confirm='P' (--confirm-single-holdout-run P)")
    out_dir = Path(out_dir)
    verify_freeze(freeze_path)
    crops = crops or d.load_selected_crops()
    inputs = [Path(feature_dir) / f"features_{c.lower()}.parquet" for c in crops] + [Path(registry_path)]
    expected = d.phase7_expected_hashes() if expected is None else expected
    missing = [str(p) for p in inputs[:-1] if str(p) not in expected]
    if missing:
        raise d.ModellingError(f"no recorded fingerprint for {missing}")
    before = d.check_inputs(inputs, expected)
    freeze_sha = file_sha256(freeze_path)
    _take_lock(out_dir, freeze_sha)
    t0, started = time.time(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg = d.registry_columns(pd.read_csv(registry_path))
    preds, logs, last_dates = [], [], {}
    for crop, path in zip(crops, inputs):
        df = pd.read_parquet(path)
        d.validate_schema(df, reg, crop)
        last_dates[crop] = df["reported_date"].max()
        by_h, _ = d.build_examples(df, reg)
        del df
        for h, ex in by_h.items():
            d.validate_examples(ex, last_dates[crop], d.feature_columns(reg, "no_weather"))
            p, lg = predict(ex, reg, crop, h, last_dates[crop], expected_last=expected_last)
            preds.append(p)
            logs += lg
        log.info("%s done (%.0fs)", crop, time.time() - t0)
        del by_h
    if d.check_inputs(inputs) != before:
        raise d.ModellingError("protected inputs changed during the holdout evaluation")
    p = pd.concat(preds, ignore_index=True)
    learned = p[p["model"] != "persistence"]                               # each row also carries the persistence value
    boot = u.bootstrap(learned, b_reps, periods=tuple(YEARS), combined=COMBINED) if len(learned) else pd.DataFrame()
    prov = pd.DataFrame([{"key": k, "value": v} for k, v in {
        "protocol": "Phase_08_Modelling_Plan.md §P", "decision_unchanged": "D-42", "freeze_manifest_sha256": freeze_sha,
        "freeze_verified": True, "inputs_sha256": json.dumps(before, sort_keys=True),
        "last_reported_date": json.dumps({c: str(x.date()) for c, x in last_dates.items()}),
        "holdout_target_sundays": f"2023-01-01 .. {expected_last.date() if expected_last is not None else 'last complete Sunday'}",
        "training_rule": "training_examples(ex, refit): every target that ended by the refit date (Phase 8 expanding window)",
        "bootstrap": f"{b_reps} replicates, seed {u.SEED}, series and market clusters, percentile 95%",
        "started_utc": started, "seconds": round(time.time() - t0, 1)}.items()])
    tables = {"holdout_results": score(p), "holdout_bootstrap": boot, "holdout_refit_log": pd.DataFrame(logs),
              "holdout_provenance": prov}
    for name, frame in tables.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
    p.to_parquet(out_dir / "holdout_predictions.parquet", index=False)
    done = {"protocol": "Phase 8 §P", "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outputs_sha256": {f"{n}.csv": file_sha256(out_dir / f"{n}.csv") for n in tables}}
    with open(out_dir / DONE.name, "x", encoding="utf-8") as fh:
        json.dump(done, fh, indent=1)
    log.info("holdout evaluation written in %.1fs", time.time() - t0)
    return tables | {"predictions": p}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", choices=["freeze", "verify", "run"])
    ap.add_argument("--confirm-single-holdout-run", default="")
    a = ap.parse_args()
    if a.command == "freeze":
        print(freeze().to_string(index=False))
    elif a.command == "verify":
        verify_freeze()
        print("holdout freeze verified")
    else:
        r = run_holdout_evaluation(a.confirm_single_holdout_run)
        print(r["holdout_results"].to_string(index=False))
