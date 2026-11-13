"""Conservative market POI matching against the existing pinned OSM files."""
import re
import json
import numpy as np
from Code.routing import osm
from Code.daily.dataset import write_json
from . import service as s

DEST=s.OUT/'phase3/market_locations.json'


def core(name):
    value=name.casefold()
    value=re.sub(r'\b(apmc|agricultural|agriculture|produce|grain|vegetable|fruit|market|yard|mandi|committee)\b','',value)
    return ''.join(c for c in value if c.isalnum())


def build():
    prices=s.current_prices();names={core(r['market']) for r in prices}
    candidates=[]
    for zone in osm.ZONES:
        directory=osm.zone_dir(zone)
        for layer,types in [('pois',(1,)),('pois_a',(5,))]:
            base=directory/f'gis_osm_{layer}_free_1'
            if not base.with_suffix('.dbf').exists():continue
            data=osm.read_dbf(base.with_suffix('.dbf'),['osm_id','name','fclass'])
            keep=np.array([bool(core(name) in names and len(core(name))>=4 and re.search(r'\b(market|mandi|apmc)\b',name,re.I)) for name in data['name']])
            seen=set()
            for idx,points in osm.read_polylines(base.with_suffix('.shp'),keep,types):
                if idx in seen:continue
                seen.add(idx)
                candidates.append({'osm_id':str(data['osm_id'][idx]),'name':data['name'][idx],'lat':float(points[:,1].mean()),'lng':float(points[:,0].mean()),'method':'OSM point' if layer=='pois' else 'OSM polygon vertex mean','source':f'Geofabrik {zone} {osm.SNAPSHOT} {layer}'})
    accepted=[];rejected=[];seen=set()
    for price in prices:
        key='|'.join(price[k] for k in ('state','district','market'))
        if key in seen:continue
        seen.add(key);reference=s.coordinate(price['state'],price['district'])
        matches=[c for c in candidates if core(c['name'])==core(price['market']) and reference and s.distance(reference,c)<=30]
        ids={c['osm_id'] for c in matches}
        if len(ids)==1:
            match=matches[0]
            accepted.append({'market_key':key,'node_id':'M:osm:'+match['osm_id'],'state':price['state'],'district':price['district'],'name':price['market'],
                             'latitude':match['lat'],'longitude':match['lng'],'precision':'Reported OSM market location, not verified entrance','verification':'reported_unverified','evidence':match})
        else:rejected.append({'market_key':key,'candidate_count':len(ids),'reason':'No unique name and 30 km reference match'})
    result={'accepted':accepted,'rejected':rejected,'candidates':len(candidates),'rule':'Exact normalized core name, explicit market/mandi/APMC label, unique OSM identity within 30 km of known district/locality reference; no fuzzy matches.',
            'attribution':'© OpenStreetMap contributors, ODbL; Geofabrik pinned 2026-10-22 extracts'}
    write_json(DEST,result);print(json.dumps({'accepted':len(accepted),'rejected':len(rejected),'candidates':len(candidates)}))


if __name__=='__main__':build()
