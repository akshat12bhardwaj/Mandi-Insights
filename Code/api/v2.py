"""
/api/v2/markets/*: recent state-level weekly prices (Code/app/data_v2.py, D-56). Read-only, observed values only.
The v1 endpoints and their boundaries in Code/api/main.py are unchanged.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException

from Code.app import data_v2 as v2

router = APIRouter(prefix="/api/v2")
Crop = Literal["Onion", "Potato", "Wheat"]
weekly = lru_cache(maxsize=1)(v2.weekly_state)


def _not_built() -> HTTPException:
    return HTTPException(503, detail={"message": "recent prices are not built in this checkout",
                                      "see": "python -B -m Code.candidates.recent_prices build"})


@router.get("/markets/meta")
def markets_meta() -> dict[str, Any]:
    m = v2.manifest()
    if m is None:
        return {"available": False, "message": "Recent prices are not built in this checkout."}
    w = weekly()
    states = {c: sorted(w.loc[(w["crop"] == c) & (w["source"] == "datagov"), "state"].unique()) for c in ("Onion", "Potato", "Wheat")}
    return {"available": True, "kind": "observed", "live": False,
            "segments": [{"source": s, "label": v2.SOURCES[s], "first_week": a, "last_week": z} for s, (a, z) in m["segments"].items()],
            "breaks": m["source_breaks"], "retrieved": m["retrieved_utc_range"][1][:10], "attribution": v2.ATTRIBUTION,
            "grade": "Fair Average Quality (FAQ) records", "states_by_crop": states}


@router.get("/markets/weekly")
def markets_weekly(crop: Crop, state: str) -> list[dict[str, Any]]:
    if v2.manifest() is None:
        raise _not_built()
    w = weekly()
    rows = w[(w["crop"] == crop) & (w["state"] == state)]
    if rows.empty:
        raise HTTPException(404, f"no recent {crop} prices for '{state}'")
    out = rows[["week_start", "source", "records", "markets", "modal_price_median"]].sort_values("week_start")
    return json.loads(out.to_json(orient="records", date_format="iso", date_unit="s"))
