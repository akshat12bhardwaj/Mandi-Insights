"""
Read-only loader for recent state-level price reporting (D-56), separate from Code/app/data.py whose boundaries are
unchanged. Serves Processed_Data/candidates/datagov_prices/reporting_v1/weekly_state.parquet (built by
Code/candidates/recent_prices.py): observed weekly medians only, never a forecast, never a market-level series.
Boundaries checked on every load: the two declared sources only, each inside its declared weeks, nothing after the
built dataset's last complete week.
"""

from __future__ import annotations

import json

import pandas as pd

from Code.candidates import recent_prices as rp
from Code.app.data import BoundaryError, _check

SOURCES = {"agmarknet_archive": "Archived AGMARKNET mandi records", "datagov": "Recent records retrieved from data.gov.in"}
ATTRIBUTION = ("Mandi prices: Directorate of Marketing and Inspection (Ministry of Agriculture and Farmers Welfare), "
               "published on data.gov.in")


def manifest() -> dict | None:
    p = rp.DEST / "reporting_manifest.json"
    return json.loads(p.read_text()) if p.exists() and rp.TABLE.exists() else None


def weekly_state() -> pd.DataFrame:
    m = manifest()
    _check(m is not None, "recent price table not built")
    df = pd.read_parquet(rp.TABLE)
    _check(set(df["source"]) <= set(SOURCES), f"unexpected source in recent prices: {set(df['source'])}")
    for s, (a, z) in m["segments"].items():
        w = df.loc[df["source"] == s, "week_start"]
        _check(w.empty or (w.min() >= pd.Timestamp(a) and w.max() <= pd.Timestamp(z)), f"{s} rows outside {a} .. {z}")
    _check(not df.duplicated(["crop", "state", "week_start"]).any(), "a week reported from two sources")
    return df


__all__ = ["BoundaryError", "SOURCES", "ATTRIBUTION", "manifest", "weekly_state"]
