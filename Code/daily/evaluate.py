"""New daily development simulation, entirely inside the old TRAINING years.

No 2019+ evaluation targets, frozen runner, protected prediction output, or
consumed test window is opened. No learned model is promoted from this study.
"""
import json
import numpy as np
import pandas as pd
from .dataset import OUT, write_json, sha
from .forecast import features, baselines, fit_models, learned_predictions, metrics, FEATURES, METHODS
from .policy import VERSION, MODEL_VERSION, IST, MIN_OBSERVATIONS, MIN_SPAN_DAYS, MIN_RECENT_OBSERVATIONS, MIN_DENSITY, MAX_AGE_DAYS

PROTOCOL = {
    "version": "daily-development-simulation-v1", "train_end": "2016-12-31",
    "development_start": "2017-01-01", "development_end": "2018-12-31",
    "reporting_delay_days": 3, "market_cap_per_crop": 12,
    "selection": "highest pre-2017 usable date count, round-robin states; >=365 training dates",
    "target_schedule": "Wednesdays; no-report days counted, never imputed",
    "models": METHODS, "feature_names": FEATURES,
    "interpretation": "Retrospective development simulation on revised archive. Publication vintages unknown; three-day delay is an assumption, not verified availability.",
    "promotion": "persistence operational default only; no learned promotion without fresh prospective evidence",
    "protected_windows": "No scoring on 2019+ or any frozen evaluation artifact. Existing decisions unchanged."
}

def simulation_rows(g):
    """Vectorized equivalent of features() under the explicitly assumed 3-day lag."""
    g = g.sort_values("date")
    d = g.date.to_numpy(dtype="datetime64[D]")
    p = g.price.to_numpy(float)
    dates = pd.date_range("2010-01-01", "2018-12-31", freq="W-WED")
    t = dates.to_numpy(dtype="datetime64[D]")
    origin = np.searchsorted(d, t - np.timedelta64(3, "D"), side="right") - 1
    target_idx = np.searchsorted(d, t)
    observed = (target_idx < len(d)) & (d[np.minimum(target_idx, len(d)-1)] == t)
    j = np.maximum(origin, 0)
    ages = (t - d[j]).astype(int)
    recent_start = np.searchsorted(d, t - np.timedelta64(365, "D"))
    recent = origin + 1 - recent_start
    eligible = ((origin + 1 >= MIN_OBSERVATIONS) & ((d[j]-d[0]).astype(int)+1 >= MIN_SPAN_DAYS)
                & (recent >= MIN_RECENT_OBSERVATIONS) & (recent/365 >= MIN_DENSITY) & (ages <= MAX_AGE_DAYS))
    valid = observed & eligible
    prices = pd.Series(p)
    mean7 = prices.rolling(7, min_periods=1).mean().to_numpy()[j]
    mean30 = prices.rolling(30, min_periods=1).mean().to_numpy()[j]
    std30 = prices.rolling(30, min_periods=1).std(ddof=0).to_numpy()[j]
    last = p[j]
    lag2, lag7 = p[np.maximum(origin-1, 0)], p[np.maximum(origin-6, 0)]
    weekday, month = dates.dayofweek.to_numpy(), dates.month.to_numpy()
    x = np.column_stack([lag2/last-1, lag7/last-1, mean7/last-1, mean30/last-1, std30/last,
                         last/lag7-1, ages, np.sin(2*np.pi*weekday/7), np.cos(2*np.pi*weekday/7),
                         np.sin(2*np.pi*month/12), np.cos(2*np.pi*month/12)])
    seasonal_idx = np.searchsorted(d, t-np.timedelta64(7, "D"))
    sj = np.minimum(seasonal_idx, len(d)-1)
    seasonal = np.where((seasonal_idx < len(d)) & (d[sj] == t-np.timedelta64(7, "D")), p[sj], last)
    rows = [{"series_id": g.iloc[0].series_id, "state": g.iloc[0].state, "date": str(dates[i].date()),
             "actual": float(p[target_idx[i]]), "x": x[i], "age_days": int(ages[i]),
             "persistence": float(last[i]), "seasonal_naive_7d": float(seasonal[i]),
             "moving_average_7obs": float(mean7[i])} for i in np.flatnonzero(valid)]
    dev = dates >= pd.Timestamp("2017-01-01")
    return rows, {"scheduled": int(dev.sum()), "no_report": int((dev & ~observed).sum()),
                  "ineligible": int((dev & observed & ~eligible).sum())}

def study(catalog):
    dest = OUT / "development"
    dest.mkdir(parents=True, exist_ok=True)
    protocol_path = dest / "protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != PROTOCOL:
        raise ValueError("Protocol differs; create a new development version")
    write_json(protocol_path, PROTOCOL)  # fixed before scoring any series
    all_scores, market_scores, age_scores, coverage, errors = [], [], [], [], []
    for crop in catalog["crops"]:
        print(f"Daily development simulation: {crop['crop']}", flush=True)
        # Predicate pushdown: evaluation never reads 2019+ values.
        h = pd.read_parquet(OUT / crop["storage"] / "observations.parquet", filters=[("date", "<=", pd.Timestamp("2018-12-31"))])
        pre = h[h.date <= "2016-12-31"].groupby(["state", "series_id"], observed=True).size().reset_index(name="n")
        pre = pre[pre.n >= 365].sort_values(["n", "series_id"], ascending=[False, True])
        pre["state_order"] = pre.groupby("state", observed=True).cumcount()
        sids = pre.sort_values(["state_order", "n", "series_id"], ascending=[True, False, True]).head(12).series_id
        train, dev = [], []
        scheduled, no_report, ineligible = 0, 0, 0
        for sid in sids:
            g = h[h.series_id == sid].copy().sort_values("date")
            examples, counts = simulation_rows(g)
            scheduled += counts["scheduled"]
            no_report += counts["no_report"]
            ineligible += counts["ineligible"]
            for row in examples:
                (dev if row["date"] >= "2017-01-01" else train).append(row)
        coverage.append({"crop": crop["crop"], "markets": int(len(sids)), "scheduled": scheduled,
                         "no_target_report": no_report, "ineligible_history": ineligible, "evaluated": len(dev),
                         "training_rows": len(train)})
        if not train or not dev:
            continue
        models = fit_models(np.stack([r["x"] for r in train]),
                            np.array([r["actual"]/r["persistence"]-1 for r in train]))
        learned = learned_predictions(models, np.stack([r["x"] for r in dev]), [r["persistence"] for r in dev])
        table = pd.DataFrame([{k:v for k,v in r.items() if k != "x"} for r in dev])
        for name, values in learned.items():
            if not np.isfinite(values).all():
                raise ValueError(f"{name}: nonfinite predictions; comparisons must share coverage")
            table[name] = values
        table["crop"] = crop["crop"]
        for name in METHODS:
            m = metrics(table.actual, table[name])
            base = metrics(table.actual, table.persistence)["mae"]
            all_scores.append({"crop": crop["crop"], "model": name, **m,
                               "skill_vs_persistence_pct": 100*(1-m["mae"]/base) if base else None,
                               "markets": table.series_id.nunique(), "nonpositive_predictions": int((table[name] <= 0).sum()),
                               "operationally_accepted": name == "persistence"})
            for sid, g in table.groupby("series_id"):
                market_scores.append({"crop": crop["crop"], "series_id": sid, "state": g.iloc[0].state,
                                      "model": name, **metrics(g.actual, g[name])})
            for age, g in table.groupby("age_days"):
                age_scores.append({"crop": crop["crop"], "age_days": age, "model": name, **metrics(g.actual, g[name])})
        table["absolute_error"] = abs(table.actual - table.persistence)
        errors.append(table[["crop", "series_id", "date", "age_days", "absolute_error"]])
    pd.DataFrame(all_scores).to_csv(dest / "by_crop.csv", index=False)
    pd.DataFrame(market_scores).to_csv(dest / "by_market.csv", index=False)
    pd.DataFrame(age_scores).to_csv(dest / "by_observation_age.csv", index=False)
    pd.DataFrame(coverage).to_csv(dest / "coverage.csv", index=False)
    if errors:
        pd.concat(errors).to_parquet(dest / "persistence_errors.parquet", index=False)
    write_json(dest / "manifest.json", {"dataset_version": VERSION, "protocol_sha256": sha(protocol_path),
               "status": "development_only_not_prospective_validation", "selected_model": "persistence",
               "model_version": MODEL_VERSION, "crops_evaluated": len(set(r["crop"] for r in all_scores)),
               "results_sha256": sha(dest / "by_crop.csv"), "protocol": PROTOCOL})
