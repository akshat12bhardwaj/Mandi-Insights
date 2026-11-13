"""Cached operational weather and sampled terrain at a labeled reference point.

Current weather is modeled, not a station observation. DEM samples do not
establish market entrances, land use, road gradients, flooding or closures.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from threading import RLock
from pathlib import Path
import hashlib
import json
import math
import requests
from Code.daily.dataset import write_json
from Code.daily.policy import IST,now_ist
from Code.weather import forecast as fc
from .build import OUT

CACHE=OUT/'phase6/environment'
POLICY=json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8'))['market_context']
CURRENT={'temperature_2m':('temperature_c','°C',-60,65),'relative_humidity_2m':('humidity_pct','%',0,100),
         'precipitation':('precipitation_mm','mm',0,1000),'wind_speed_10m':('wind_kmh','km/h',0,500)}
DAILY={'temperature_2m_max':('tmax_c','°C',-60,65),'temperature_2m_min':('tmin_c','°C',-60,65),
       'precipitation_sum':('rain_mm','mm',0,1000),'precipitation_probability_max':('rain_probability_pct','%',0,100)}

def key(coordinate):return hashlib.sha256(f"{coordinate['lat']:.5f}|{coordinate['lng']:.5f}".encode()).hexdigest()[:20]
def valid(value,lo,hi):return value is None or (not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and lo<=value<=hi)

def weather_fetch(lat,lon):
    response=requests.get(fc.URL,params={'latitude':lat,'longitude':lon,'current':','.join([*CURRENT,'weather_code']),
        'daily':','.join([*DAILY,'weather_code']),'timezone':'Asia/Kolkata','forecast_days':3},timeout=(3,6))
    response.raise_for_status();return parse_weather(response.json())

def parse_weather(body):
    current=body.get('current',{});units=body.get('current_units',{});parsed=None
    if current.get('time'):
        stamp=datetime.fromisoformat(current['time'])
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=IST)
        parsed={'time':stamp.isoformat(),'kind':'modeled_current','interval_seconds':current.get('interval')}
        for field,(name,unit,lo,hi) in CURRENT.items():
            value=current.get(field)
            if value is not None and (units.get(field)!=unit or not valid(value,lo,hi)):raise ValueError('Invalid current-weather value or unit')
            parsed[name]=value
        if units.get('weather_code') == 'wmo code' and type(current.get('weather_code')) is int:
            parsed['weather_code'] = current['weather_code']
        if all(parsed.get(name) is None for name,_,_,_ in CURRENT.values()):parsed=None
    daily=body.get('daily',{});dates=daily.get('time',[]);daily_units=body.get('daily_units',{})
    if not isinstance(dates,list) or len(dates)!=3 or len(set(dates))!=3:raise ValueError('Invalid three-day weather coverage')
    actual_dates=[datetime.fromisoformat(d).date() for d in dates]
    if any((b-a).days!=1 for a,b in zip(actual_dates,actual_dates[1:])):raise ValueError('Nonconsecutive forecast dates')
    days=[{'date':d} for d in dates]
    for field,(name,unit,lo,hi) in DAILY.items():
        values=daily.get(field,[])
        if len(values)!=3 or daily_units.get(field)!=unit:raise ValueError('Invalid daily-weather coverage or unit')
        for row,value in zip(days,values):
            if not valid(value,lo,hi):raise ValueError('Invalid daily-weather value')
            row[name]=value
    days=[d for d in days if any(d.get(name) is not None for name,_,_,_ in DAILY.values())]
    codes = daily.get('weather_code')
    if daily_units.get('weather_code') == 'wmo code' and isinstance(codes, list) and len(codes) == 3:
        by_date = dict(zip(dates, codes))
        for row in days:
            if type(by_date[row['date']]) is int:
                row['weather_code'] = by_date[row['date']]
    return {'current':parsed,'outlook':days,'provider':'Open-Meteo','basis':'Modeled outdoor conditions and forecast at the mapped reference; not station measurements'}


def regional_weather():
    if not fc.enabled():
        return []
    references = [('Delhi', 28.61, 77.21), ('Jaipur', 26.91, 75.79), ('Patna', 25.59, 85.14),
                  ('Guwahati', 26.14, 91.74), ('Ahmedabad', 23.02, 72.57), ('Nagpur', 21.15, 79.09),
                  ('Kolkata', 22.57, 88.36), ('Hyderabad', 17.39, 78.49), ('Bengaluru', 12.97, 77.59)]

    def read_reference(reference):
        name, lat, lng = reference
        point = {'lat': lat, 'lng': lng}
        weather = lookup(point, 'weather', fetch=True)
        current = weather['data'].get('current') if weather and not weather['stale'] else None
        if current and current.get('weather_code') is not None:
            return {'name': name, **point, 'weather_code': current['weather_code'],
                    'temperature_c': current.get('temperature_c')}
        return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for row in pool.map(read_reference, references) if row is not None]

def terrain_fetch(lat,lon):
    step=POLICY['terrain_sample_offset_degrees']
    lats=[lat,lat+step,lat-step,lat,lat];lons=[lon,lon,lon,lon+step,lon-step]
    response=requests.get('https://api.open-meteo.com/v1/elevation',params={'latitude':','.join(map(str,lats)),'longitude':','.join(map(str,lons))},timeout=(3,6))
    response.raise_for_status();values=response.json().get('elevation',[])
    if len(values)!=5 or any(v is None or not valid(v,-500,9000) for v in values):raise ValueError('Invalid elevation sample')
    relief=max(values)-min(values);center=values[0]
    return {'available':True,'elevation_m':center,'sample_relief_m':round(relief,1),'sample_points':5,
        'band':'Low elevation reference' if center<200 else 'Mid elevation reference' if center<1000 else 'High elevation reference',
        'setting':'Variable elevations in the sampled vicinity' if relief>=POLICY['terrain_relief_caution_m'] else 'Limited variation in the sampled vicinity',
        'logistics_note':'Check approach-road gradients; the vicinity sample is not a surveyed road profile.' if relief>=POLICY['terrain_relief_caution_m'] else 'Elevation samples do not establish road quality, land use or flood safety.',
        'source':'Copernicus DEM GLO-90 via Open-Meteo','source_url':'https://open-meteo.com/en/docs/elevation-api',
        'basis':'Center and four points about 3 km away; 90 m DEM, approximate at the location reference'}

@lru_cache(maxsize=256)
def read(path,mtime):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else None
    except (OSError,ValueError):return None

@lru_cache(maxsize=512)
def cache_lock(identifier,kind):return RLock()


def lookup(coordinate,kind,fetch=False):
    # Collapse concurrent requests for the same reference and cache file.
    with cache_lock(key(coordinate),kind):return _lookup(coordinate,kind,fetch)


def _lookup(coordinate,kind,fetch=False):
    path=CACHE/f'{key(coordinate)}-{kind}.json';now=datetime.now(timezone.utc)
    held=read(str(path),path.stat().st_mtime_ns) if path.exists() else None
    lifetime=timedelta(hours=3) if kind=='weather' else timedelta(days=30)
    try:
        age=now-datetime.fromisoformat(held['retrieved_at']) if held and isinstance(held.get('data'),dict) else None
        if age is None or age.total_seconds()<0:held=None;age=None
    except (ValueError,TypeError,KeyError):held=None;age=None
    if held and age<lifetime:return {**held,'stale':False}
    if not fetch:return {**held,'stale':True} if held and age<(timedelta(days=2) if kind=='weather' else timedelta(days=365)) else None
    failure=path.with_suffix('.failure.json')
    try:
        if failure.exists() and timedelta(0)<=now-datetime.fromisoformat(json.loads(failure.read_text())['at'])<timedelta(minutes=15):return lookup(coordinate,kind,False)
    except (OSError,ValueError,TypeError,KeyError):pass
    try:
        data=(weather_fetch if kind=='weather' else terrain_fetch)(coordinate['lat'],coordinate['lng'])
        result={'retrieved_at':now.isoformat(),'data':data,'stale':False}
        try:write_json(path,result)
        except OSError:pass
        return result
    except (requests.RequestException,ValueError,TypeError,KeyError):
        try:write_json(failure,{'at':now.isoformat()})
        except OSError:pass
        return lookup(coordinate,kind,False)

def context(coordinate,fetch=False):
    if not coordinate:return {'available':False,'current':None,'outlook':[],'terrain':{'available':False},'cautions':[],'reason':'No accepted geographic reference; no location was guessed.'}
    if fetch:
        with ThreadPoolExecutor(max_workers=2) as pool:
            w=pool.submit(lookup,coordinate,'weather',fc.enabled());t=pool.submit(lookup,coordinate,'terrain',True)
            weather,terrain=w.result(),t.result()
    else:weather,terrain=lookup(coordinate,'weather'),lookup(coordinate,'terrain')
    data=weather['data'] if weather and fc.enabled() else {};current=data.get('current')
    if current and abs((datetime.now(timezone.utc)-datetime.fromisoformat(current['time'])).total_seconds())>10800:current=None
    days=[r for r in data.get('outlook',[]) if r['date']>=str(now_ist().date())][:3]
    terrain_data={**terrain['data'],'retrieved_at':terrain['retrieved_at'],'stale':terrain['stale']} if terrain else {'available':False,'setting':'Terrain samples unavailable','logistics_note':'No landform or road gradient was inferred.'}
    cautions=[]
    if weather and not weather['stale']:
        if any(r.get('rain_mm') is not None and r['rain_mm']>=POLICY['rain_caution_mm_day'] for r in days):cautions.append('Forecast rain reaches the project handling-caution threshold; review loading and covered storage. Not an official warning or road-closure report.')
        if current and current.get('wind_kmh') is not None and current['wind_kmh']>=POLICY['wind_caution_kmh']:cautions.append('Modeled wind is elevated; review loading arrangements. No automatic trade rejection.')
    if terrain_data.get('sample_relief_m',0)>=POLICY['terrain_relief_caution_m']:cautions.append(terrain_data['logistics_note'])
    return {'available':bool(current or days),'current':current,'outlook':days,'weather_stale':weather['stale'] if weather else False,
        'weather_retrieved_at':weather['retrieved_at'] if weather else None,'weather_basis':data.get('basis','Weather unavailable; no conditions assumed.'),
        'terrain':terrain_data,'coordinate':coordinate,'cautions':cautions,'used_in_price_model':False,
        'decision_policy':'Weather and terrain supply practical cautions; no fabricated price adjustment, confidence score or automatic rejection.',
        'attribution':'Weather: Open-Meteo (CC BY 4.0). Elevation: Copernicus DEM via Open-Meteo.'}
