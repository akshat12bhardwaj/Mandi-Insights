"""Versioned current forecast context; never enters a price-model evaluation."""
from pathlib import Path
import requests
from Code.weather import forecast as fc

CACHE=Path("Processed_Data/weather_forecast/decision_context_v2")


def fetch(lat,lon):
    response=requests.get(fc.URL,params={"latitude":lat,"longitude":lon,"daily":",".join(fc.DAILY),
        "hourly":"relative_humidity_2m,wind_speed_10m","timezone":"Asia/Kolkata","forecast_days":7},timeout=10)
    if response.status_code!=200:
        raise fc.ForecastError("Weather provider unavailable")
    try:
        body=response.json();days=fc.parse(body)
        hourly=body.get("hourly",{});units=body.get("hourly_units",{})
        times=hourly.get("time",[])
        if len(times)!=len(set(times)):
            raise fc.ForecastError("Duplicate hourly timestamps")
        for column,unit,name,lo,hi in [("relative_humidity_2m","%","humidity_mean_pct",0,100),("wind_speed_10m","km/h","wind_max_kmh",0,500)]:
            values=hourly.get(column,[])
            if units.get(column)!=unit or len(values)!=len(times) or not times:
                raise fc.ForecastError("Invalid hourly weather units or coverage")
            for day in days:
                group=[v for t,v in zip(times,values) if t[:10]==day["date"]]
                if len(group)!=24 or any(v is None for v in group):
                    day[name]=None;continue
                if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not lo<=v<=hi for v in group):
                    raise fc.ForecastError("Invalid hourly weather value")
                day[name]=round(sum(group)/len(group),1) if column=="relative_humidity_2m" else max(group)
        return days
    except (ValueError,TypeError,KeyError) as exc:
        raise fc.ForecastError("Malformed weather response") from exc


def context(key,lat,lon):
    return fc.forecast(key,lat,lon,cache=CACHE,fetcher=fetch)
