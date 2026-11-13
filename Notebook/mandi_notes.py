"""Read-only paths, bounded data access and shared presentation for the notebook series."""
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import json
import math
import os
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # Existing project functions resolve their artifacts from the repository root.
os.environ.setdefault("OMP_NUM_THREADS", "2")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from cycler import cycler
import numpy as np
import pandas as pd
from IPython.display import display
try:
    import ipywidgets as widgets
except ImportError:
    widgets = None

DATA = ROOT / "Processed_Data"
DAILY = DATA / "daily_v1"
INTEL = DATA / "intelligence_v1"
RAW = ROOT / "Dataset/India Commodity Wise Mandi Dataset"
PH8 = DATA / "modelling/phase08"
CANDIDATE = DATA / "candidates/datagov_prices/experiments"
CROPS = ["Onion", "Potato", "Wheat"]
FOREST, SAGE, CREAM, GRAY, GOLD = "#205940", "#90ad91", "#f7f4ec", "#526058", "#b8793b"
plt.rcParams.update({
    "figure.facecolor": CREAM, "axes.facecolor": CREAM, "axes.edgecolor": SAGE,
    "axes.labelcolor": FOREST, "text.color": FOREST, "xtick.color": GRAY,
    "ytick.color": GRAY, "grid.color": "#dedfd2", "axes.spines.top": False,
    "axes.spines.right": False, "axes.prop_cycle": cycler(color=[FOREST, SAGE, GOLD, GRAY]),
    "figure.figsize": (9, 3.8), "figure.dpi": 100, "axes.titleweight": "bold",
})


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def diagram(labels):
    fig, ax = plt.subplots(figsize=(11, 1.8), layout="constrained")
    ax.set(xlim=(0, len(labels)), ylim=(0, 1))
    ax.axis("off")
    for i, label in enumerate(labels):
        ax.add_patch(FancyBboxPatch((i + .035, .22), .82, .55, boxstyle="round,pad=.02",
                                   facecolor=FOREST if i == 0 else "#e0eadc", edgecolor=SAGE))
        ax.text(i + .445, .5, label, ha="center", va="center",
                color="white" if i == 0 else FOREST, fontsize=10, weight="bold")
        if i < len(labels) - 1:
            ax.annotate("", (i + 1.01, .5), (i + .88, .5), arrowprops={"arrowstyle": "->", "color": FOREST})
    plt.show()


def controls(render, **options):
    """Render a static default and connect optional controls to the same renderer."""
    render(**{name: values[0] for name, values in options.items()})
    if widgets is None or not hasattr(widgets, "interactive"):
        return
    panel = widgets.interactive(render, {"manual": True, "manual_name": "Update view"}, **{
        name: widgets.Dropdown(options=values, description=name.replace("_", " ").title())
        for name, values in options.items()
    })
    display(panel)


@lru_cache(maxsize=3)
def archive_sample(crop):
    """Deterministic evenly spaced archive sample restricted to development dates."""
    catalog = read_json(DAILY / "catalog.json")
    entry = next(row for row in catalog["crops"] if row["crop"] == crop)
    path = DAILY / entry["storage"] / "observations.parquet"
    columns = ["date", "price", "state", "district", "market", "series_id", "variety"]
    table = pd.read_parquet(path, columns=columns, filters=[("date", "<", pd.Timestamp("2019-01-01"))])
    step = max(1, math.ceil(len(table) / 30000))
    return table.iloc[::step].reset_index(drop=True)


def development_market(crop="Onion"):
    sample = archive_sample(crop)
    sid = sample["series_id"].value_counts().index[0]
    entry = next(row for row in read_json(DAILY / "catalog.json")["crops"] if row["crop"] == crop)
    history = pd.read_parquet(
        DAILY / entry["storage"] / "observations.parquet",
        columns=["date", "price", "available_at", "market", "state"],
        filters=[("series_id", "==", sid), ("date", "<", pd.Timestamp("2019-01-01"))],
    ).sort_values("date").reset_index(drop=True)
    # The archive's recorded ingestion date is in 2026. Reproduce the
    # development protocol's explicit three-day delay for historical examples.
    history["available_at"] = (history.date + pd.Timedelta(days=3)).dt.tz_localize("UTC")
    return history


def publication():
    return read_json(DAILY / "serving.json")


def auxiliary(name, snapshot=None):
    snapshot = snapshot or publication()
    return read_json(DAILY / snapshot["auxiliary"][name])


def predictions(snapshot=None):
    snapshot = snapshot or publication()
    path = (DAILY / snapshot["batch"]["path"]).as_uri()
    with closing(sqlite3.connect(path + "?mode=ro&immutable=1", uri=True)) as db:
        rows = db.execute("SELECT payload FROM predictions WHERE price IS NOT NULL")
        return pd.DataFrame(json.loads(raw) for raw, in rows)


def planned_trade():
    """Use a published compatible pair with the app's cached routes and planner."""
    from Code.intelligence import service as service
    snap = publication()
    rows = auxiliary("strategies", snap)["rows"]
    stored = next((row for row in rows if row["trading_mode"] == "interstate"), rows[0])
    # Replay the saved pair only, using its saved observations and batch date.
    # This also works after the live batch expires.
    from datetime import datetime
    from unittest.mock import patch
    stamp = datetime.fromisoformat(snap["batch"]["issue"]).replace(hour=8, minute=0, second=0, microsecond=0)
    with patch.object(service, "current_prices", return_value=[stored["buy"], stored["sell"]]), patch.object(service, "now_ist", return_value=stamp):
        result = service.strategies(buy_id=stored["buy"]["series_id"], sell_id=stored["sell"]["series_id"],
                                    mode=stored["trading_mode"], integrated=True, details=True)
    return result["rows"][0], stamp
