"""Availability-gated features for a future independent daily weather study.

The local revised weather archive has no publication vintages. It must NOT be
backdated into a historical forecast. No model is promoted by this module.
"""
import numpy as np
import pandas as pd
from Code.daily.forecast import FEATURES


def observed_features(weather, target, issue):
    issue=pd.Timestamp(issue)
    if issue.tzinfo is None:
        raise ValueError("Weather cutoff must be timezone-aware")
    if "available_at" not in weather:
        return None,"Original observation availability timestamps are missing."
    target=pd.Timestamp(target).tz_localize(None).normalize()
    dates=pd.to_datetime(weather.date).dt.tz_localize(None).dt.normalize()
    available=pd.to_datetime(weather.available_at,utc=True,errors="coerce",format="mixed")
    past=weather.loc[(dates<target)&(available<=issue.tz_convert("UTC"))].copy()
    past["date"]=dates.loc[past.index]
    window=past[(past.date>=target-pd.Timedelta(days=7))].sort_values("date")
    columns=["rain_sum","temperature_2m_max","relative_humidity_2m_mean"]
    if len(window)!=7 or window.date.nunique()!=7 or any(c not in window for c in columns):
        return None,"Seven complete, previously available weather observations are required."
    values=window[columns].apply(pd.to_numeric,errors="coerce")
    if (not np.isfinite(values.to_numpy()).all() or not values.rain_sum.between(0,1000).all()
            or not values.temperature_2m_max.between(-50,60).all()
            or not values.relative_humidity_2m_mean.between(0,100).all()):
        return None,"Invalid or missing weather observations."
    return np.array([values.rain_sum.sum(),values.temperature_2m_max.mean(),values.relative_humidity_2m_mean.mean()]),None


def variant_vectors(price_features, weather=None, arrivals=None):
    """A/B/C/D experiment inputs. Absence is not imputed as zero weather/arrivals.

    A uses the existing past-price/age features; B additionally uses cyclic
    calendar features; C/D require time-gated observations supplied by a caller.
    Training/evaluation must be offline, chronological and on matched rows.
    """
    x=np.asarray(price_features,float)
    if x.shape!=(len(FEATURES),) or not np.isfinite(x).all():
        raise ValueError("Invalid price features")
    result={"A_price":x[:-4],"B_price_calendar":x,"C_weather":None,"D_weather_arrivals":None}
    if weather is not None and np.isfinite(weather).all():
        result["C_weather"]=np.concatenate([x,weather])
        if arrivals is not None and np.isfinite(arrivals).all():
            result["D_weather_arrivals"]=np.concatenate([x,weather,arrivals])
    return result


def metadata():
    return {"used_in_price_model":False,"daily_validation":"not_available",
            "reason":"No local cutoff-vintage historical weather observations for a valid new daily comparison; operational persistence retained.",
            "archive_note":"The existing 2001–2022 weather archive has missing original availability timestamps. Do not infer publication time from observation dates.",
            "prior_evidence":"The closed weekly weather study failed its acceptance rule for all three legacy crops; it is not daily validation.",
            "comparison_status":{"A_price":"supported","B_price_calendar":"saved daily development study",
                                 "C_weather":"blocked_missing_availability_vintages","D_weather_arrivals":"blocked_missing_aligned_recent_arrivals_and_weather_vintages"},
            "feature_version":"daily-weather-availability-v1"}
