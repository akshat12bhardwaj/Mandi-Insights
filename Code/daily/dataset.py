"""Read-only raw inputs -> separately versioned, traceable local parquet datasets.

Reuses the project's R01-R09 price rules. No source identities are bridged and
no published/retrieval date is inferred from the reporting date.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from Code.cleaning.pipeline import duplicate_structure, trailing_price_reference, PRICES, MODAL
from Code.integration.pipeline import MANDI_COLUMNS, MANDI_KEY, MANDI_VALUES
from Code.utils.data_audit import load_mandi_file, parse_dates_fast, MANDI_DIR
from .policy import VERSION, KEY, eligibility, series_id, text, now_ist

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Processed_Data" / "daily_v1"
CATEGORIES = {
    "Cereals and grains": ["Wheat", "Rice", "Paddy(Dhan)(Common)", "Maize", "Bajra(Pearl Millet-Cumbu)", "Jowar(Sorghum)", "Barley (Jau)"],
    "Pulses and legumes": ["Bengal Gram(Gram)(Whole)", "Arhar (Tur-Red Gram)(Whole)", "Green Gram (Moong)(Whole)", "Black Gram (Urd Beans)(Whole)", "Lentil (Masur)(Whole)"],
    "Vegetables": ["Onion", "Potato", "Tomato", "Brinjal", "Cauliflower", "Cabbage", "Bhindi(Ladies Finger)", "Green Chilli", "Cucumbar(Kheera)", "Bottle gourd", "Pumpkin", "Bitter gourd", "Carrot", "Raddish", "Garlic", "Ginger(Green)", "Sweet Potato", "Tapioca"],
    "Fruits": ["Banana", "Apple", "Lemon", "Mango", "Papaya", "Grapes", "Orange", "Pineapple", "Jack Fruit", "Litchi", "Peach"],
    "Oilseeds": ["Soyabean", "Mustard", "Groundnut", "Castor Seed", "Sunflower", "Linseed", "Safflower"],
    "Commercial or cash crops": ["Cotton", "Jute", "Rubber", "Coffee", "Tea", "Sugarcane", "Dry Chillies", "Black pepper"],
}
CROP_CATEGORY = {c: cat for cat, names in CATEGORIES.items() for c in names}

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(2**20), b""):
            h.update(part)
    return h.hexdigest()

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    # Windows sync/indexing tools can briefly hold a destination open. Preserve
    # atomic replacement and retry only the transient file-lock operation.
    for attempt in range(6):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt==5: raise
            time.sleep(.1*(attempt+1))

def clean_prices(df):
    """Same R01/R03/R04/R07/R08/R09 price decisions; arrivals not modeled."""
    df = df.copy()
    ds = duplicate_structure(df)
    conflict = ds.n_versions > 1
    redundant = ds.copy_rank > 0
    for c in PRICES:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df[c] = df[c].where(np.isfinite(df[c]) & (df[c] > 0))
    mn, mx, md = (df[c] for c in PRICES)
    bad_range = (mn > mx) | (md < mn) | (md > mx)
    ref = trailing_price_reference(df.loc[~redundant])
    ratio = pd.concat([np.maximum(df[c] / ref, ref / df[c]) for c in PRICES], axis=1).max(axis=1)
    usable = ~conflict & ~redundant & ~bad_range & md.notna() & ~(ratio >= 50)
    valid_key = df[KEY].notna().all(axis=1) & df.reported_date.notna()
    usable &= valid_key
    return df.loc[usable].copy(), {
        "raw_records": len(df), "usable_records": int(usable.sum()), "duplicate_records": int(redundant.sum()),
        "conflicting_records": int(conflict.sum()), "anomalous_records": int((bad_range | md.isna() | (ratio >= 50)).sum()),
        "invalid_key_records": int((~valid_key).sum()), "review_records": int(((ratio >= 10) & (ratio < 50)).sum())}

def summarize_series(df, target):
    work = df.copy()
    work["week"] = work.date.dt.to_period("W-SUN").astype(str)
    rows = []
    for sid, g in work.groupby("series_id", observed=True, sort=True):
        dates = g.date.drop_duplicates().sort_values()
        e = eligibility(dates, target)
        span = (dates.iloc[-1] - dates.iloc[0]).days + 1
        rows.append({"series_id": sid, **g.iloc[0][KEY].to_dict(), "source": g.iloc[0].source,
                     "grade": g.iloc[0].grade, "usable_observations": len(dates), "weekly_observations": g.week.nunique(),
                     "first_date": str(dates.iloc[0].date()), "last_date": str(dates.iloc[-1].date()),
                     "missing_calendar_frequency": 1 - len(dates) / span,
                     "median_reporting_gap_days": float(dates.diff().dt.days.median()) if len(dates) > 1 else None,
                     "reference_365_eligible": len(dates) >= 365,
                     "daily_eligible_at_source_end": e["status"] in ("prediction_available", "stale_prediction"),
                     "current_status": eligibility(dates, now_ist().date())["status"]})
    return pd.DataFrame(rows)

def audit_crop(crop):
    path = ROOT / MANDI_DIR / f"{crop}.csv"
    dest = OUT / "archive" / hashlib.sha256(crop.encode()).hexdigest()[:12]
    dest.mkdir(parents=True, exist_ok=True)
    fingerprint = sha(path)
    if (dest / "summary.json").exists():
        saved = json.loads((dest / "summary.json").read_text(encoding="utf-8"))
        if saved["source_sha256"] == fingerprint:
            return saved
        raise ValueError("Archive source changed; use a new daily dataset version instead of overwriting this snapshot")
    print(f"Auditing {crop} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
    raw = load_mandi_file(path.name).rename(columns=MANDI_COLUMNS)
    raw["reported_date"] = parse_dates_fast(raw.reported_date)
    for c in KEY + ["commodity_group"]:
        raw[c] = raw[c].map(lambda v: text(v) if pd.notna(v) and text(v) else None).astype("category")
    raw["source_row"] = np.arange(len(raw))
    raw["crop"] = crop
    good, counts = clean_prices(raw)
    # Group is not in the daily identity. Conflicting groups on the same day are excluded, never averaged.
    ambiguous = good.duplicated(KEY + ["reported_date"], keep=False)
    counts["ambiguous_daily_key_records"] = int(ambiguous.sum())
    good = good.loc[~ambiguous].copy()
    counts["usable_records"] = len(good)
    good["series_id"] = good.groupby(KEY, observed=True).ngroup().map(
        {i: series_id(crop, "agmarknet_archive", list(k)) for i, k in enumerate(good.groupby(KEY, observed=True).groups)})
    # Explicit record provenance survives preprocessing. Source row is zero-based after header.
    good = good.rename(columns={"reported_date": "date", MODAL: "price"})
    good["source"] = "agmarknet_archive"
    good["grade"] = "unspecified"
    good["available_at"] = now_ist().isoformat()
    good["availability_basis"] = "first_ingested_by_daily_extension; original publication vintage unknown"
    cols = ["crop", *KEY, "series_id", "date", "price", "source", "grade", "source_row", "available_at", "availability_basis"]
    good = good[cols].sort_values(["series_id", "date"]).reset_index(drop=True)
    good.to_parquet(dest / "observations.parquet", index=False)
    end = good.date.max() + pd.Timedelta(days=1)
    series = summarize_series(good, end)
    series.to_parquet(dest / "series.parquet", index=False)
    result = {"crop": crop, "category": CROP_CATEGORY[crop], **counts,
              "source_path": str(path.relative_to(ROOT)), "source_sha256": fingerprint,
              "storage": str(dest.relative_to(OUT)), "first_date": str(good.date.min().date()),
              "last_date": str(good.date.max().date()), "reporting_years": int(good.date.dt.year.nunique()),
              "states": int(good.state.nunique()), "districts": int(good[KEY[:2]].drop_duplicates().shape[0]),
              "markets": int(good[KEY[:3]].drop_duplicates().shape[0]), "varieties": int(good.variety.nunique()),
              "weekly_observations": int(series.weekly_observations.sum()),
              "reference_365_series": int(series.reference_365_eligible.sum()),
              "daily_eligible_series": int(series.daily_eligible_at_source_end.sum()),
              "median_missing_calendar_frequency": float(series.missing_calendar_frequency.median()),
              "median_reporting_gap_days": float(series.median_reporting_gap_days.median()),
              "fresh_series_now": int(series.current_status.isin(["prediction_available", "stale_prediction"]).sum()),
              "observations_sha256": sha(dest / "observations.parquet")}
    write_json(dest / "summary.json", result)
    return result

def discover():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted((ROOT / MANDI_DIR).glob("*.csv"))
    pd.DataFrame([{"commodity": p.stem, "bytes": p.stat().st_size,
                   "in_daily_audit": p.stem in CROP_CATEGORY} for p in files]).to_csv(OUT / "inventory.csv", index=False)
    # Includes top-volume vegetables omitted by the old APY-based feasibility audit,
    # whole pulses, cereals, oilseeds and cash crops. Tiny unrelated commodities aren't read.
    results = [audit_crop(c) for c in CROP_CATEGORY if (ROOT / MANDI_DIR / f"{c}.csv").exists()]
    ranked = pd.DataFrame(results).sort_values(["daily_eligible_series", "reference_365_series", "usable_records"], ascending=False)
    ranked["rank"] = range(1, len(ranked) + 1)
    viable = ranked[ranked.daily_eligible_series >= 10]
    chosen = {"Onion", "Potato", "Wheat"}
    # Minimum diversity only among empirically viable crops; remaining slots by continuity rank.
    for category, n in {"Cereals and grains": 3, "Pulses and legumes": 2, "Vegetables": 3,
                        "Fruits": 2, "Oilseeds": 2, "Commercial or cash crops": 1}.items():
        chosen.update(viable[viable.category == category].head(n).crop)
    for c in viable.crop:
        if len(chosen) >= 20:
            break
        chosen.add(c)
    ranked["selected"] = ranked.crop.isin(chosen)
    ranked["selection_reason"] = np.where(ranked.selected, "retained legacy / category minimum / continuity rank", "lower continuity rank or category allocation")
    ranked.to_csv(OUT / "crop_ranking.csv", index=False)
    selected = ranked[ranked.selected].to_dict("records")
    write_json(OUT / "catalog.json", {"version": VERSION, "built_at": now_ist().isoformat(), "crops": selected,
               "candidate_count": len(ranked), "inventory_count": len(files),
               "selection_rule": "retain legacy three; >=10 eligible series; category minima 3/2/3/2/2/1 then eligible-series rank",
               "warning": "Historical support does not imply fresh coverage. See per-series eligibility."})
    print(f"Selected {len(selected)} of {len(ranked)} audited crops", flush=True)
