"""
Seven-day weather forecast for the 46 verified district points (D-57). Operational context only: never a model input,
never joined to the historical weather panel or its vintages, never an official warning.

Provider: Open-Meteo forecast API (key-less; free tier is non-commercial, < 10,000 calls/day; data CC BY 4.0 with
attribution, https://open-meteo.com/en/terms). One request per point, cached on disk for TTL; a point is never asked
for more than once per TTL, so 46 points stay far inside the limits.
Failure: the last good copy is served marked stale with its retrieval time; with no copy the forecast is unavailable.
Values the provider leaves empty stay None (never zero). Switch off with BDA_WEATHER_FORECAST=0.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = {"precipitation_sum": ("rain_mm", "mm", 0, 1000), "temperature_2m_max": ("tmax_c", "°C", -40, 60),
         "precipitation_probability_max": ("rain_probability_pct", "%", 0, 100)}
DAYS = 7
TTL = timedelta(hours=3)
KEEP = timedelta(days=2)                    # an older copy is no longer shown, even as stale
CACHE = Path("Processed_Data/weather_forecast/cache")
PROVIDER = "Open-Meteo"
ATTRIBUTION = {"text": "Weather forecast by Open-Meteo.com", "licence": "CC BY 4.0", "link": "https://open-meteo.com/"}
HEAVY_RAIN_MM = 64.5                        # IMD "heavy rainfall" lower bound for 24 h accumulation


class ForecastError(RuntimeError):
    pass


def enabled() -> bool:
    return os.environ.get("BDA_WEATHER_FORECAST", "1") != "0"


def parse(body: dict) -> list[dict]:
    """Validate the provider response and return one row per day; raises ForecastError on anything unexpected."""
    d, units = body.get("daily"), body.get("daily_units", {})
    if not isinstance(d, dict) or not isinstance(d.get("time"), list) or len(d["time"]) != DAYS:
        raise ForecastError("response has no 7-day daily block")
    rows = [{"date": t} for t in d["time"]]
    for src, (name, unit, lo, hi) in DAILY.items():
        vals = d.get(src)
        if not isinstance(vals, list) or len(vals) != DAYS:
            raise ForecastError(f"{src} missing or not {DAYS} days")
        if units.get(src) != unit:
            raise ForecastError(f"{src} unit {units.get(src)!r}, expected {unit!r}")
        for r, v in zip(rows, vals):
            if v is not None and (not isinstance(v, (int, float)) or not lo <= v <= hi):
                raise ForecastError(f"{src} value {v!r} outside {lo}..{hi}")
            r[name] = v
    dates = [datetime.fromisoformat(r["date"]).date() for r in rows]
    if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
        raise ForecastError("forecast days are not consecutive")
    return rows


def fetch(lat: float, lon: float, timeout: float = 10) -> list[dict]:
    r = requests.get(URL, params={"latitude": lat, "longitude": lon, "daily": ",".join(DAILY), "timezone": "Asia/Kolkata",
                                  "forecast_days": DAYS}, timeout=timeout)
    if r.status_code != 200:
        raise ForecastError(f"provider returned HTTP {r.status_code}")
    try:
        return parse(r.json())
    except ValueError as e:
        raise ForecastError("provider returned a non-JSON body") from e


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry), encoding="utf-8")
    os.replace(tmp, path)


def forecast(key: str, lat: float, lon: float, now: datetime | None = None, cache: Path = CACHE, fetcher=fetch) -> dict:
    """{available, stale, retrieved_utc, days, reason}. `key` names the verified point (one cache file per point)."""
    now = now or datetime.now(timezone.utc)
    base = {"provider": PROVIDER, "attribution": ATTRIBUTION, "kind": "forecast", "official_warning": False}
    if not enabled():
        return base | {"available": False, "stale": False, "retrieved_utc": None, "days": [], "reason": "weather forecasts are switched off"}
    path = Path(cache) / f"{key}.json"
    held = _read(path)
    age = now - datetime.fromisoformat(held["retrieved_utc"]) if held else None
    if held and age < TTL:
        return base | {"available": True, "stale": False, "retrieved_utc": held["retrieved_utc"], "days": held["days"], "reason": None}
    try:
        days = fetcher(lat, lon)
    except (ForecastError, requests.RequestException) as e:
        if held and age < KEEP:
            return base | {"available": True, "stale": True, "retrieved_utc": held["retrieved_utc"], "days": held["days"],
                           "reason": f"latest update failed ({type(e).__name__}); showing the last good forecast"}
        return base | {"available": False, "stale": False, "retrieved_utc": None, "days": [], "reason": "the forecast provider is not reachable"}
    entry = {"retrieved_utc": now.isoformat(timespec="seconds"), "lat": lat, "lon": lon, "days": days}
    _write(path, entry)
    return base | {"available": True, "stale": False, "retrieved_utc": entry["retrieved_utc"], "days": days, "reason": None}


def flags(days: list[dict]) -> list[dict]:
    """Days whose forecast rain reaches the IMD heavy-rainfall threshold. A forecast, not an official warning."""
    return [{"date": d["date"], "rain_mm": d["rain_mm"]} for d in days if d.get("rain_mm") is not None and d["rain_mm"] >= HEAVY_RAIN_MM]
