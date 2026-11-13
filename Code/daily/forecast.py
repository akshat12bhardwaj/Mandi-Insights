"""Time-safe operational features and independent, development-only comparisons."""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .policy import eligibility, MAX_AGE_DAYS

FEATURES = ["lag2_ratio", "lag7_ratio", "mean7_ratio", "mean30_ratio", "volatility30",
            "momentum", "age_days", "weekday_sin", "weekday_cos", "month_sin", "month_cos"]
METHODS = ["persistence", "seasonal_naive_7d", "moving_average_7obs", "ridge", "hist_gradient_boosting"]

def known_history(history, target, issue):
    issue = pd.Timestamp(issue)
    if issue.tzinfo is None:
        raise ValueError("Forecast issue timestamp must include a timezone")
    target = pd.Timestamp(target).normalize().tz_localize(None)
    h = history.copy()
    h["date"] = pd.to_datetime(h.date).dt.tz_localize(None).dt.normalize()
    available = pd.to_datetime(h.available_at, utc=True, format="mixed")
    h = h[(h.date < target) & (available <= issue.tz_convert("UTC"))]
    h = h[np.isfinite(h.price) & (h.price > 0)].sort_values("date")
    if h.date.duplicated().any():
        raise ValueError("Ambiguous daily series; preprocessing must resolve/exclude conflicting keys")
    return h

def features(history, target, issue):
    h = known_history(history, target, issue)
    e = eligibility(h.date, target)
    if h.empty:
        return None, e, h
    p = h.price.to_numpy(float)
    last = p[-1]
    t = pd.Timestamp(target)
    z = p[-30:]
    v = [p[-min(2, len(p))] / last - 1, p[-min(7, len(p))] / last - 1,
         p[-7:].mean() / last - 1, z.mean() / last - 1, z.std() / last,
         last / p[-min(7, len(p))] - 1, e["age_days"],
         np.sin(2*np.pi*t.dayofweek/7), np.cos(2*np.pi*t.dayofweek/7),
         np.sin(2*np.pi*t.month/12), np.cos(2*np.pi*t.month/12)]
    return np.asarray(v, dtype=float), e, h

def baselines(h, target):
    p = h.price.to_numpy(float)
    t = pd.Timestamp(target)
    # Exact calendar-week price, explicitly falls back when that day wasn't reported.
    season = h.loc[h.date == t - pd.Timedelta(days=7), "price"]
    return {"persistence": float(p[-1]), "seasonal_naive_7d": float(season.iloc[-1] if len(season) else p[-1]),
            "moving_average_7obs": float(p[-7:].mean())}

def fit_models(x, relative_target):
    return {"ridge": make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(x, relative_target),
            "hist_gradient_boosting": HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7,
                 min_samples_leaf=30, l2_regularization=10, random_state=711, early_stopping=False).fit(x, relative_target)}

def learned_predictions(models, x, last):
    # Invalid learned predictions are rejected, never silently clipped into a plausible price.
    return {name: np.asarray(last) * (1 + model.predict(x)) for name, model in models.items()}

def metrics(actual, predicted):
    a, p = np.asarray(actual, float), np.asarray(predicted, float)
    return {"rows": len(a), "mae": float(np.abs(a-p).mean()), "rmse": float(np.sqrt(np.mean((a-p)**2))),
            "smape_pct": float(np.mean(200*np.abs(a-p)/np.maximum(np.abs(a)+np.abs(p), 1e-9)))}
