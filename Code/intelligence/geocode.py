"""Bounded locality references, never claimed as exact mandi coordinates."""
import json
import math
import time
import unicodedata
import requests
from Code.daily.dataset import write_json
from Code.daily.policy import now_ist
from . import service as s

PATH=s.OUT/'phase2/district_references.json'
URL='https://geocoding-api.open-meteo.com/v1/search'


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value).casefold() if c.isalnum())


def choose(results,state,district):
    exact=[r for r in results if r.get('country_code')=='IN' and fold(r.get('admin1',''))==fold(state)
           and fold(r.get('name',''))==fold(district) and r.get('feature_code','').startswith(('PPL','ADM2'))
           and isinstance(r.get('latitude'),(int,float)) and isinstance(r.get('longitude'),(int,float))
           and math.isfinite(r['latitude']) and math.isfinite(r['longitude']) and 6<=r['latitude']<=38 and 67<=r['longitude']<=98]
    if not exact:return None
    if max(r['latitude'] for r in exact)-min(r['latitude'] for r in exact)>.03 or max(r['longitude'] for r in exact)-min(r['longitude'] for r in exact)>.03:
        return None
    return max(exact,key=lambda r:r.get('population',0))


def build(budget=35,crops=None):
    held=json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {'rows':[],'rejected':[]}
    accepted={(r['state'],r['district']) for r in held['rows']}
    targets=sorted({(r['state'],r['district']) for r in s.current_prices() if (not crops or r['crop'] in crops) and not s.coordinate(r['state'],r['district'])})
    calls=0
    with requests.Session() as client:
        for state,district in targets:
            if (state,district) in accepted:continue
            if calls>=budget:break
            calls+=1
            try:
                response=client.get(URL,params={'name':district+', '+state,'countryCode':'IN','count':20,'language':'en','format':'json'},timeout=(5,15))
                response.raise_for_status();body=response.json()
                result=choose(body.get('results',[]),state,district)
            except (requests.RequestException,ValueError):
                held['rejected'].append({'state':state,'district':district,'reason':'Lookup unavailable'});continue
            if result:
                held['rows'].append({'node_id':f'G:{state}|{district}','name':district,'state':state,'district':district,
                    'latitude':result['latitude'],'longitude':result['longitude'],'verification':'geocoded_locality',
                    'location_meaning':'GeoNames locality reference, approximate for district; not a market entrance',
                    'source':'Open-Meteo geocoding / GeoNames','source_id':result['id'],'source_url':URL,
                    'retrieved_at':now_ist().isoformat(),'source_admin1':result['admin1'],'source_admin2':result.get('admin2')})
            else:held['rejected'].append({'state':state,'district':district,'reason':'No unambiguous exact locality/state match'})
            held['attribution']='Location data: GeoNames via Open-Meteo geocoding; approximate locality references'
            write_json(PATH,held);time.sleep(.3)
    s._nodes.cache_clear();s.route_options.cache_clear()
    print(json.dumps({'calls':calls,'accepted_references':len(held['rows']),'unresolved':len(held['rejected'])}))


if __name__=='__main__':build()
