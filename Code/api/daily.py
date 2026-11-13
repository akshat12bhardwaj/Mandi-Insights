"""Versioned daily-price endpoints in the existing FastAPI application.

No collection, training, evaluation or batch generation occurs in requests.
"""
from __future__ import annotations
from functools import lru_cache
from contextvars import ContextVar
import json
import sqlite3
from typing import Any, Literal
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from Code.daily import operational as op
from Code.daily.dataset import OUT, sha
from Code.daily.policy import VERSION, MODEL_VERSION, commodity, now_ist, MAX_AGE_DAYS, MIN_OBSERVATIONS, MIN_SPAN_DAYS, MIN_DENSITY

router = APIRouter(prefix="/api/v3/daily", tags=["Daily price extension"])
BUILDING=ContextVar('building_intelligence_snapshot',default=False)

def serving():
    path=OUT/'serving.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() and not BUILDING.get() else None

def auxiliary_path(name,default):
    held=serving()
    return OUT/held['auxiliary'][name] if held and name in held.get('auxiliary',{}) else default

class Prediction(BaseModel):
    crop: str
    category: str
    state: str
    district: str
    market: str
    variety: str
    series_id: str
    source: str
    grade: str
    kind: Literal["prediction"]
    unit: Literal["INR/quintal"]
    target_date: str
    forecast_issue_timestamp: str
    dataset_version: str
    model_version: str
    model: Literal["persistence"]
    status: Literal["prediction_available", "stale_prediction", "stale_unavailable", "insufficient_history", "batch_expired"]
    predicted_modal_price: float | None = Field(gt=0)
    last_observed_price: float | None = Field(gt=0)
    last_observation_date: str | None
    last_observation_available_at: str | None
    data_freshness: dict[str, Any]
    observed_today: float | None
    observed_today_status: str
    uncertainty_interval: None = None
    validation: str
    provenance: dict[str, Any]
    historical_error: dict[str, Any] | None = None
    previous_forecast: dict[str, Any] | None = None

def _signature():
    try:
        held=serving()
        release = held['release'] if held else json.loads((OUT / "release.json").read_text())
        batch = held['batch'] if held else json.loads((OUT / "batch.json").read_text())
        dest = OUT / "releases" / release["release"]
        paths = [OUT / "release.json", OUT / "batch.json", dest / "manifest.json", dest / "model.json",
                 dest / "registry.parquet", OUT / batch["path"]]
        return (str(OUT),json.dumps(release,sort_keys=True),json.dumps(batch,sort_keys=True), *[(p.stat().st_mtime_ns, p.stat().st_size) for p in paths])
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "Daily prices not built. Run python -B -m Code.daily build outside the API.")

@lru_cache(maxsize=2)
def _snapshot(signature):
    try:
        dest, manifest, model = op.load_release(json.loads(signature[1]))
        registry = pd.read_parquet(dest / "registry.parquet")
        pointer = json.loads(signature[2])
        if pointer["dataset_version"] != manifest["dataset_version"]:
            raise ValueError("Batch dataset version mismatch")
        path = OUT / pointer["path"]
        if sha(path) != pointer["sha256"]:
            raise ValueError("Batch checksum mismatch")
        batch = op.BatchStore(path)
        if not batch.validate(registry,manifest["dataset_version"]):
            raise ValueError("Batch artifact identities or versions mismatch")
        return manifest, registry, batch, pointer
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise HTTPException(503, "Daily artifacts are incomplete or inconsistent; rebuild the daily release and batch.") from exc

def snapshot():
    return _snapshot(_signature())

def crop_rows(crop):
    m, r, b, p = snapshot()
    crop = commodity(crop)
    if crop not in {c["crop"] for c in m["catalog"]["crops"]}:
        raise HTTPException(404, "Unsupported crop")
    return r[r.crop == crop]

def rows(frame):
    return json.loads(frame.to_json(orient="records"))

@router.get("/crops")
def crops():
    m, r, b, p = snapshot()
    return {"dataset_version": m["dataset_version"], "crops": m["catalog"]["crops"]}

@router.get("/categories")
def categories():
    m, r, b, p = snapshot()
    return sorted({c["category"] for c in m["catalog"]["crops"]})

@router.get("/locations")
def locations(crop: str, state: str | None = None):
    r = crop_rows(crop)
    if state is not None:
        r = r[r.state == state]
    if r.empty:
        raise HTTPException(404, "Unsupported state for this crop")
    return rows(r[["state", "district"]].drop_duplicates().sort_values(["state", "district"]))

@router.get("/markets")
def markets(crop: str, state: str, district: str):
    r = crop_rows(crop)
    r = r[(r.state == state) & (r.district == district)]
    if r.empty:
        raise HTTPException(404, "Unsupported district for this crop and state")
    return rows(r[["series_id", "market", "variety", "source", "grade", "first_date", "last_date", "usable_observations"]]
                .sort_values(["market", "last_date", "variety"], ascending=[True, False, True]))

def error_information(crop):
    path = OUT / "development/by_crop.csv"
    if not path.exists():
        from Code.intelligence.learning import score
        return score(crop)
    table = pd.read_csv(path)
    r = table[(table.crop == crop) & (table.model == "persistence")]
    if r.empty:
        from Code.intelligence.learning import score
        return score(crop)
    result = r.iloc[0].to_dict()
    return {**result, "period": "2017–2018", "scope": "12 training-selected market-variety series maximum; reporting-delay simulation, not live validation"}

@router.get("/today", response_model=Prediction)
def today(series_id: str):
    m, r, b, pointer = snapshot()
    if series_id not in b:
        raise HTTPException(404, "Unsupported market-variety series")
    value = json.loads(json.dumps(b[series_id]))
    target = str(now_ist().date())
    if value["target_date"] != target:
        value["previous_forecast"]={"target_date":value["target_date"],"issued_at":value["forecast_issue_timestamp"],
                                    "prediction":value["predicted_modal_price"],"kind":"previous_run_not_current"}
        value.update(status="batch_expired", target_date=target, predicted_modal_price=None, observed_today=None,
                     observed_today_status="not_checked_in_current_batch")
        value["data_freshness"]["age_days"] = ((pd.Timestamp(target)-pd.Timestamp(value["last_observation_date"])).days
                                                 if value["last_observation_date"] else None)
    value["historical_error"] = error_information(value["crop"])
    return value

@lru_cache(maxsize=32)
def _history(path: str, fingerprint: str, sid: str):
    if sha(path) != fingerprint.split(":", 1)[0]:
        raise HTTPException(503, "Observation artifact checksum mismatch")
    return pd.read_parquet(path, filters=[("series_id", "==", sid)]).sort_values("date")

@router.get("/history")
def history(series_id: str, limit: int = Query(90, ge=1, le=365)):
    m, r, b, pointer = snapshot()
    match = r[r.series_id == series_id]
    if match.empty:
        raise HTTPException(404, "Unsupported market-variety series")
    source = next(s for s in m["sources"] if s["storage"] == match.iloc[0].storage)
    path = OUT / source["storage"] / "observations.parquet"
    # Cache invalidates on file modification even if an external process alters it.
    try:
        stat = path.stat()
        result = _history(str(path), source["observations_sha256"] + f":{stat.st_mtime_ns}:{stat.st_size}", series_id)
    except OSError as exc:
        raise HTTPException(503, "Observed history artifact is unavailable; restore it or rebuild the daily dataset.") from exc
    return {"kind": "observed", "unit": "INR/quintal", "source": match.iloc[0].source,
            "points": rows(result[["date", "price", "available_at"]].tail(limit).assign(date=lambda x: x.date.dt.strftime("%Y-%m-%d")))}

@router.get("/metadata")
def metadata():
    m, r, b, pointer = snapshot()
    return {"version": VERSION, "dataset_version": m["dataset_version"], "model_version": MODEL_VERSION,
            "target_date_ist": str(now_ist().date()), "batch_target_date": pointer["target_date"],
            "forecast_issue_timestamp": pointer["issue"], "crops": len(m["catalog"]["crops"]),
            "series": len(r), "maximum_observation_age_days": MAX_AGE_DAYS,
            "eligibility": {"minimum_observations": MIN_OBSERVATIONS, "minimum_span_days": MIN_SPAN_DAYS, "minimum_recent_year_density": MIN_DENSITY},
            "model": "persistence", "source_separation": m["source_separation"],
            "limitations": ["No publication-vintage archive; historical error is a reporting-delay simulation.",
                             "No calibrated live uncertainty interval. Severely stale series receive no prediction."],
            "attribution": "Mandi prices: DMI / AGMARKNET; recent observations via data.gov.in. Local use; redistribution terms not established."}

@router.get("/freshness")
def freshness():
    m, r, b, pointer = snapshot()
    current = str(now_ist().date()) == pointer["target_date"]
    statuses,eligible = b.summary()
    return {"target_date": str(now_ist().date()), "batch_current": current,
            "latest_observation_by_crop": r.groupby("crop").last_date.max().to_dict(),
            "eligible_predictions": eligible if current else 0,
            "statuses": statuses if current else {"batch_expired": len(r)}}
