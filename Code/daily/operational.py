"""Build model artifacts and deterministic forecast batches outside API requests."""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import pandas as pd
from .dataset import OUT, ROOT, sha, write_json, summarize_series, clean_prices
from .forecast import known_history
from .policy import VERSION, MODEL_VERSION, KEY, IST, now_ist, eligibility, eligibility_summary, series_id,text

RECENT_POLICY_VERSION = "daily-recent-v3-normalized-vintages"
LEGACY_FAQ_CROPS = {"Onion", "Potato", "Wheat"}

def import_recent(crop):
    """Read established observed records only; never import evaluation predictions.

    Keep raw market identity and grade. No cross-era canonical market mapping,
    pooled-grade price or source-vintage reconstruction is asserted.
    """
    src = ROOT / "Processed_Data/candidates/datagov_prices/dataset_v1_2" / f"records_{crop.lower()}.parquet"
    cols = ["State", "District", "Market", "Variety", "Grade", "reported_date", "modal_price_rs_per_quintal",
            "retrieved_utc", "record_ref", "usable_for_target", "in_faq_only"]
    inputs, frames = [], []
    if src.exists():
        r = pd.read_parquet(src, columns=cols)
        r = r[r.usable_for_target & r.in_faq_only].copy()
        r = r.rename(columns={"State": "state", "District": "district", "Market": "market", "Variety": "variety",
                          "Grade": "grade", "reported_date": "date", "modal_price_rs_per_quintal": "price",
                          "retrieved_utc": "available_at", "record_ref": "source_row"})
        frames.append(r)
        inputs.append({"path":str(src.relative_to(ROOT)),"sha256":sha(src)})
    refresh = OUT / "refresh_manifest.json"
    if refresh.exists():
        partitions = sorted(json.loads(refresh.read_text())["partitions"].values(), key=lambda p: (p["crop"],p["date"]))
        covered_dates=pd.to_datetime([p["date"] for p in partitions if p["crop"]==crop])
        # Complete newer crop-day snapshots supersede the legacy operational
        # view for those dates, including empty/retracted reports. The original
        # candidate parquet and earlier releases remain unchanged.
        if frames and len(covered_dates):
            frames[0]=frames[0].loc[~frames[0].date.isin(covered_dates)].copy()
        fresh = []
        for p in partitions:
            if p["crop"] != crop:
                continue
            path = ROOT / p["path"]
            if sha(path) != p["file_sha256"]:
                raise ValueError("Refreshed raw partition checksum mismatch")
            raw = json.loads(path.read_text(encoding="utf-8"))
            first_seen={}
            for vintage in [*p.get("revisions",[]),p]:
                vintage_path=ROOT/vintage["path"]
                if sha(vintage_path)!=vintage["file_sha256"]:
                    raise ValueError("Raw revision checksum mismatch")
                body=json.loads(vintage_path.read_text(encoding="utf-8"))
                inputs.append({"path":vintage["path"],"sha256":vintage["file_sha256"]})
                for idx,row in enumerate(body["records"]):
                    key=json.dumps(row,sort_keys=True)
                    first_seen.setdefault(key,(body["retrieved_at"],f"{vintage['path']}#{idx}"))
            # Only the latest verified partition is operational; removed rows are
            # not resurrected. Unchanged records retain actual earlier availability.
            for row in raw["records"]:
                available,reference=first_seen[json.dumps(row,sort_keys=True)]
                fresh.append({**row,"available_at":available,"record_ref":reference})
        if fresh:
            f = pd.DataFrame(fresh).rename(columns={"State":"state","District":"district","Market":"market","Variety":"variety",
                "Grade":"commodity_group","Min_Price":"min_price_rs_per_quintal","Max_Price":"max_price_rs_per_quintal",
                "Modal_Price":"modal_price_rs_per_quintal"})
            f["reported_date"] = pd.to_datetime(f.Arrival_Date,format="%d/%m/%Y",errors="coerce")
            f["source_row"],f["crop"],f["arrivals_tonnes"] = range(len(f)),crop,float("nan")
            f,_ = clean_prices(f)
            # FAQ is the established three-crop contract, not a valid grade
            # restriction for fruit. New crops retain separately identified grades.
            if crop in LEGACY_FAQ_CROPS:
                f = f[f.commodity_group=="FAQ"]
            f = f.rename(columns={"commodity_group":"grade","reported_date":"date",
                                                          "modal_price_rs_per_quintal":"price"})
            f["source_row"] = f.record_ref
            frames.append(f)
    if not frames:
        return None
    r = pd.concat(frames,ignore_index=True)
    if r.empty:
        return None
    for key in KEY+["grade"]:
        r[key]=r[key].map(lambda v:text(v) if pd.notna(v) else None)
    r["source"] = "datagov"
    r["crop"] = crop
    r["availability_basis"] = "actual_retrieval_timestamp; not original publication timestamp"
    # Identical values retain the earliest ACTUAL retrieval time, never a fabricated publication time.
    r["_available"] = pd.to_datetime(r.available_at,utc=True,format="mixed")
    r = r.sort_values("_available").drop_duplicates(KEY + ["grade", "date", "price"])
    r = r.loc[~r.duplicated(KEY + ["grade", "date"], keep=False)].copy()
    identities = r[KEY + ["grade"]].drop_duplicates()
    identities["series_id"] = [series_id(crop, "datagov", [row[k] for k in KEY], row["grade"])
                               for row in identities.to_dict("records")]
    r = r.merge(identities, on=KEY + ["grade"], validate="many_to_one")
    r = r[["crop", *KEY, "series_id", "date", "price", "source", "grade", "source_row", "available_at", "availability_basis"]]
    import hashlib
    fingerprint = hashlib.sha256(json.dumps({"inputs":inputs,"processing_policy":RECENT_POLICY_VERSION},sort_keys=True).encode()).hexdigest()
    dest = OUT / "recent" / f"{hashlib.sha256(crop.encode()).hexdigest()[:12]}-{fingerprint[:12]}"
    dest.mkdir(parents=True, exist_ok=True)
    r = r.sort_values(["series_id", "date"]).reset_index(drop=True)
    # Content-addressed source partitions are immutable. Reuse unchanged parquet
    # rather than repeating market-level summaries on every daily update.
    if not (dest / "observations.parquet").exists() or not (dest / "series.parquet").exists():
        r.to_parquet(dest / "observations.parquet", index=False)
        summarize_series(r, r.date.max() + pd.Timedelta(days=1)).to_parquet(dest / "series.parquet", index=False)
    return {"crop": crop, "storage": str(dest.relative_to(OUT)), "source_path": [v["path"] for v in inputs],
            "processing_policy": RECENT_POLICY_VERSION,
            "source_sha256": fingerprint, "observations_sha256": sha(dest / "observations.parquet"),
            "last_date": str(r.date.max().date()), "records": len(r)}

def release(publish=True, catalog_override=None):
    catalog = catalog_override if catalog_override is not None else json.loads((OUT / "catalog.json").read_text(encoding="utf-8"))
    sources, registry = [], []
    for c in catalog["crops"]:
        inputs = [c] if c.get('storage') else []
        recent = import_recent(c["crop"])
        if recent:
            inputs.append(recent)
        for source in inputs:
            source = {k: source[k] for k in ("crop", "storage", "source_path", "source_sha256", "observations_sha256")}
            if source["storage"].startswith("recent"):
                source["processing_policy"] = RECENT_POLICY_VERSION
            sources.append(source)
            s = pd.read_parquet(OUT / source["storage"] / "series.parquet")
            s["crop"], s["category"], s["storage"] = c["crop"], c["category"], source["storage"]
            registry.append(s)
    # Snapshot IDs describe source content, not the clock or a mutable 'latest' path.
    import hashlib
    identity_content = {"sources": sources, "catalog_override": catalog} if catalog_override is not None else sources
    identity = hashlib.sha256(json.dumps(identity_content, sort_keys=True).encode()).hexdigest()[:16]
    dest = OUT / "releases" / identity
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "manifest.json").exists():
        existing = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        if existing["sources"] != sources:
            raise ValueError("Release identity collision")
        if publish:
            write_json(OUT / "release.json", {"release": identity, "manifest_sha256": sha(dest / "manifest.json")})
        return dest, existing
    dataset_version = f"{VERSION}:{identity}"
    pd.concat(registry, ignore_index=True).to_parquet(dest / "registry.parquet", index=False)
    artifact = {"model_version": MODEL_VERSION, "dataset_version": dataset_version, "model": "persistence",
                "approved_for": "operational conservative baseline; no claim of prospective learned-model superiority",
                "prediction": "last valid observation known at issue and reported strictly before target date",
                "trained_parameters": None, "validation": "development simulation only; see development/protocol.json"}
    write_json(dest / "model.json", artifact)
    manifest = {"dataset_version": dataset_version, "model_version": MODEL_VERSION, "built_at": now_ist().isoformat(),
                "catalog": catalog, "sources": sources, "registry_sha256": sha(dest / "registry.parquet"),
                "model_sha256": sha(dest / "model.json"), "source_separation": "archive and datagov market/variety/grade identities remain distinct"}
    write_json(dest / "manifest.json", manifest)
    if publish:
        write_json(OUT / "release.json", {"release": identity, "manifest_sha256": sha(dest / "manifest.json")})
    return dest, manifest

def load_release(pointer=None):
    pointer = pointer if pointer is not None else json.loads((OUT / "release.json").read_text())
    dest = OUT / "releases" / pointer["release"]
    if sha(dest / "manifest.json") != pointer["manifest_sha256"]:
        raise ValueError("Dataset manifest checksum mismatch")
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    if sha(dest / "model.json") != manifest["model_sha256"] or sha(dest / "registry.parquet") != manifest["registry_sha256"]:
        raise ValueError("Model/registry artifact checksum mismatch")
    model = json.loads((dest / "model.json").read_text())
    if model["dataset_version"] != manifest["dataset_version"] or model["model_version"] != MODEL_VERSION or model["model"] != "persistence":
        raise ValueError("Model and dataset versions are incompatible")
    return dest, manifest, model

def forecast_one(history, metadata, issue, dataset_version):
    issue = pd.Timestamp(issue)
    if issue.tzinfo is None:
        raise ValueError("Issue timestamp must be timezone-aware")
    issue = issue.tz_convert(IST)
    target = issue.date()
    known = known_history(history, target, issue)
    e = eligibility(known.date, target)
    observed = history[(history.date == pd.Timestamp(target)) & (pd.to_datetime(history.available_at, utc=True, format="mixed") <= issue.tz_convert("UTC"))]
    last = known.iloc[-1] if len(known) else None
    return prediction_payload(metadata, issue, dataset_version, e, last, float(observed.iloc[-1].price) if len(observed) else None)


def prediction_payload(metadata, issue, dataset_version, e, last, observed_today):
    eligible = e["status"] in ("prediction_available", "stale_prediction")
    return {**{k: metadata[k] for k in ["crop", "category", *KEY, "series_id", "source", "grade"]},
            "kind": "prediction", "unit": "INR/quintal", "target_date": str(issue.date()), "forecast_issue_timestamp": issue.isoformat(),
            "dataset_version": dataset_version, "model_version": MODEL_VERSION, "model": "persistence",
            "status": e["status"], "predicted_modal_price": float(last["price"]) if eligible else None,
            "last_observed_price": float(last["price"]) if last is not None else None,
            "last_observation_date": str(last["date"].date()) if last is not None else None,
            "last_observation_available_at": str(last["available_at"]) if last is not None else None,
            "data_freshness": e, "observed_today": observed_today,
            "observed_today_status": "fresh_observed_price_available" if observed_today is not None else "not_reported_or_not_yet_retrieved",
            "uncertainty_interval": None,
            "validation": "Historical development simulation only; no calibrated live confidence interval.",
            "provenance": {"source": metadata["source"], "source_row": str(last["source_row"]) if last is not None else None,
                           "availability_basis": str(last["availability_basis"]) if last is not None else None}}


def forecast_source(history, registry, issue, dataset_version):
    """Apply identical cutoff and eligibility rules once per source, then group.

    Missing days stay absent. No calendar expansion or per-series date parsing.
    """
    import numpy as np
    issue = pd.Timestamp(issue)
    if issue.tzinfo is None:
        raise ValueError("Issue timestamp must be timezone-aware")
    issue = issue.tz_convert(IST)
    target = pd.Timestamp(issue.date())
    h = history.copy()
    h["date"] = pd.to_datetime(h.date).dt.tz_localize(None).dt.normalize()
    available = pd.to_datetime(h.available_at, utc=True, format="mixed") <= issue.tz_convert("UTC")
    known = h.loc[available & (h.date < target) & np.isfinite(h.price) & (h.price > 0)].sort_values(["series_id","date"])
    if known.duplicated(["series_id","date"]).any():
        raise ValueError("Ambiguous daily series; preprocessing must resolve/exclude conflicting keys")
    grouped = known.groupby("series_id", observed=True)
    summary = grouped.date.agg(["size","min","max"])
    recent = known.loc[known.date >= target-pd.Timedelta(days=365)].groupby("series_id", observed=True).size()
    summary["recent"] = recent.reindex(summary.index, fill_value=0)
    policies = {sid: eligibility_summary(int(row.size),int((row.max-row.min).days)+1,int(row.recent),int((target-row.max).days))
                for sid,row in zip(summary.index,summary.itertuples(index=False))}
    last = known.drop_duplicates("series_id",keep="last").set_index("series_id").to_dict("index")
    actuals = h.loc[available & (h.date == target)].drop_duplicates("series_id",keep="last").set_index("series_id").price.to_dict()
    identities = registry.loc[sorted(h.series_id.unique())].to_dict("index")
    return [prediction_payload({"series_id":sid,**meta},issue,dataset_version,
                               policies.get(sid) or eligibility_summary(0,0,0,None),last.get(sid),
                               float(actuals[sid]) if sid in actuals else None) for sid,meta in identities.items()]

def batch(issue=None,release_bundle=None):
    if release_bundle is None:
        dest, manifest, model = load_release()
    else:
        dest,manifest=release_bundle
        if sha(dest/"registry.parquet")!=manifest["registry_sha256"] or sha(dest/"model.json")!=manifest["model_sha256"]:
            raise ValueError("Prepared release artifact checksum mismatch")
        model=json.loads((dest/"model.json").read_text())
        if model["dataset_version"]!=manifest["dataset_version"] or model["model_version"]!=MODEL_VERSION:
            raise ValueError("Prepared model version mismatch")
    issue = pd.Timestamp(issue if issue is not None else now_ist())
    if issue.tzinfo is None:
        raise ValueError("Issue timestamp must be timezone-aware")
    if issue < pd.Timestamp(manifest["built_at"]):
        raise ValueError("Cannot backdate operational inference before this dataset/model release existed")
    registry = pd.read_parquet(dest / "registry.parquet").set_index("series_id")
    rows = []
    for source in manifest["sources"]:
        path = OUT / source["storage"] / "observations.parquet"
        if sha(path) != source["observations_sha256"]:
            raise ValueError("Dataset observations changed; build a new dataset version")
        h = pd.read_parquet(path)
        rows.extend(forecast_source(h, registry, issue, manifest["dataset_version"]))
    publish_batch(rows, dest, manifest, issue)
    print(f"Batch: {len(rows)} market-variety series, {sum(r['predicted_modal_price'] is not None for r in rows)} eligible predictions", flush=True)
    return rows

def publish_batch(rows, dest, manifest, issue):
    """An indexed local SQLite artifact avoids loading all 70,000 JSON forecasts per API worker."""
    out = dest / "batches" / issue.tz_convert(IST).strftime("%Y%m%dT%H%M%S%f%z")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "predictions.sqlite"
    temp = path.with_suffix(".tmp")
    with closing(sqlite3.connect(temp)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS predictions (series_id TEXT PRIMARY KEY, status TEXT, price REAL, dataset_version TEXT, model_version TEXT, payload TEXT NOT NULL)")
        db.execute("DELETE FROM predictions")
        db.executemany("INSERT INTO predictions VALUES (?,?,?,?,?,?)", [(r["series_id"],r["status"],r["predicted_modal_price"],
                       r["dataset_version"],r["model_version"],json.dumps(r,ensure_ascii=False,allow_nan=False)) for r in rows])
        db.commit()
    temp.replace(path)
    write_json(OUT / "batch.json", {"path": str(path.relative_to(OUT)),
               "sha256": sha(path), "dataset_version": manifest["dataset_version"],
               "issue": issue.isoformat(), "target_date": str(issue.tz_convert(IST).date()), "records": len(rows)})

class BatchStore:
    def __init__(self,path):
        self.path = Path(path)
    def connect(self):
        return closing(sqlite3.connect(self.path.as_uri()+"?mode=ro",uri=True))
    def __contains__(self,sid):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM predictions WHERE series_id=?",(sid,)).fetchone() is not None
    def __getitem__(self,sid):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM predictions WHERE series_id=?",(sid,)).fetchone()
        if row is None:
            raise KeyError(sid)
        return json.loads(row[0])
    def validate(self,registry,version):
        with self.connect() as db:
            ids = {r[0] for r in db.execute("SELECT series_id FROM predictions")}
            bad = db.execute("SELECT COUNT(*) FROM predictions WHERE dataset_version!=? OR model_version!=?",(version,MODEL_VERSION)).fetchone()[0]
        return ids == set(registry.series_id) and not bad
    def summary(self):
        with self.connect() as db:
            statuses = dict(db.execute("SELECT status, COUNT(*) FROM predictions GROUP BY status"))
            eligible = db.execute("SELECT COUNT(*) FROM predictions WHERE price IS NOT NULL").fetchone()[0]
        return statuses,eligible
