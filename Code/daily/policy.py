"""Daily v1 contract: conservative defaults fixed before the availability audit."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
import unicodedata

VERSION = "daily-prices-v1"
MODEL_VERSION = "daily-persistence-v1"
IST = timezone(timedelta(hours=5, minutes=30))  # Windows: no system tz database required.
MIN_OBSERVATIONS = 180
MIN_SPAN_DAYS = 365
MIN_RECENT_OBSERVATIONS = 60
MIN_DENSITY = .25
MAX_AGE_DAYS = 7
KEY = ["state", "district", "market", "variety"]

# Deliberately no fuzzy matching, paddy/rice, whole/split pulses or variety merges.
ALIASES = {"soybean": "Soyabean", "chana": "Bengal Gram(Gram)(Whole)",
           "gram": "Bengal Gram(Gram)(Whole)", "moong": "Green Gram (Moong)(Whole)",
           "urad": "Black Gram (Urd Beans)(Whole)", "tur": "Arhar (Tur-Red Gram)(Whole)",
           "paddy": "Paddy(Dhan)(Common)", "bajra": "Bajra(Pearl Millet-Cumbu)"}

def text(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()

def commodity(value):
    s = text(value)
    return ALIASES.get(s.casefold(), s)

def series_id(crop, source, values, grade="unspecified"):
    import json
    return hashlib.sha256(json.dumps([crop, source, *values, grade], ensure_ascii=False).encode()).hexdigest()[:24]

def now_ist():
    return datetime.now(IST)

def eligibility(dates, target):
    """Only actual, distinct dates strictly before target; no calendar imputation."""
    import pandas as pd
    t = pd.Timestamp(target).normalize()
    d = pd.DatetimeIndex(dates).normalize().unique().sort_values()
    d = d[d < t]
    if not len(d):
        return {"status": "insufficient_history", "observations": 0, "age_days": None,
                "recent_observations": 0, "span_days": 0, "density": 0.0}
    age = int((t - d[-1]).days)
    span = int((d[-1] - d[0]).days) + 1
    recent = int((d >= t - pd.Timedelta(days=365)).sum())
    return eligibility_summary(len(d), span, recent, age)


def eligibility_summary(observations, span, recent, age):
    """Shared policy for scalar histories and grouped batch summaries."""
    if not observations:
        return {"status": "insufficient_history", "observations": 0, "age_days": None,
                "recent_observations": 0, "span_days": 0, "density": 0.0}
    density = recent / 365
    enough = observations >= MIN_OBSERVATIONS and span >= MIN_SPAN_DAYS
    status = ("insufficient_history" if not enough else "stale_unavailable" if age > MAX_AGE_DAYS
              else "insufficient_history" if recent < MIN_RECENT_OBSERVATIONS or density < MIN_DENSITY
              else "prediction_available" if age <= 3 else "stale_prediction")
    return {"status": status, "observations": observations, "age_days": age,
            "recent_observations": recent, "span_days": span, "density": round(density, 6)}
