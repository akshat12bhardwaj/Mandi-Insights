"""Bounded exact market-town lookups, never asserted as mandi entrances."""
import json
import re
import time
import requests
from Code.daily.dataset import write_json
from Code.daily.policy import now_ist
from . import service as s
from .geocode import choose,URL

PATH=s.OUT/'phase5/locality_references.json'

def town(market):
    value=re.sub(r'\s+APMC$','',market,flags=re.I).strip()
    # Composite market names require evidence linking their individual places.
    return value if '(' not in value and ')' not in value else None

def build(crop='Green Chilli',budget=10):
    held=json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {'rows':[],'rejected':[],'requests':0}
    known={r['market_key'] for r in held['rows']};calls=0
    with requests.Session() as client:
        for row in s.current_prices():
            if row['crop']!=crop or s.market_coordinate(row):continue
            key='|'.join(row[k] for k in ('state','district','market'));name=town(row['market'])
            if key in known or not name:continue
            if calls>=budget:break
            calls+=1;held['requests']+=1
            response=client.get(URL,params={'name':name,'countryCode':'IN','count':20,'language':'en','format':'json'},timeout=(5,15))
            if response.status_code==429:break
            response.raise_for_status();result=choose(response.json().get('results',[]),row['state'],name)
            if result:
                held['rows'].append({'node_id':'G:market:'+str(result['id']),'market_key':key,'name':name,
                    'state':row['state'],'district':row['district'],'latitude':result['latitude'],'longitude':result['longitude'],
                    'verification':'geocoded_locality','precision':'GeoNames market-town reference; not a verified mandi entrance',
                    'location_meaning':'Unique exact town/state match; approximate market reference',
                    'source':'GeoNames via Open-Meteo','source_id':result['id'],'source_admin2':result.get('admin2'),
                    'retrieved_at':now_ist().isoformat(),'evidence':result})
                known.add(key)
            else:held['rejected'].append({'market_key':key,'reason':'No unique exact town/state match'})
            held['attribution']='GeoNames via Open-Meteo; https://open-meteo.com/en/docs/geocoding-api'
            write_json(PATH,held);time.sleep(.5)
    s._nodes.cache_clear();s.route_options.cache_clear()
    print(json.dumps({'calls':calls,'accepted':len(held['rows']),'rejected':len(held['rejected'])}))

if __name__=='__main__':build()
