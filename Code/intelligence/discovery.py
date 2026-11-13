"""Offline commodity inventory and unbounded-by-count operational catalog.

Discovery reads existing inventories and accepted partitions, never a full
provider download. Only validated archive/accepted-price sources are published.
"""
import json
import pandas as pd
from Code.daily.dataset import ROOT,OUT as DAILY,CROP_CATEGORY,sha,write_json
from Code.daily.policy import text
from .build import OUT


def discover():
    ranking=DAILY/'crop_ranking.csv'
    ranked=pd.read_csv(ranking).fillna('') if ranking.exists() else pd.DataFrame()
    crops={}
    for row in ranked.to_dict('records'):
        name=text(row['crop']);folder=DAILY/row['storage']
        if not (folder/'observations.parquet').exists() or not (folder/'series.parquet').exists():continue
        crops[name]={**row,'crop':name,'selected':True,'selection_reason':'Validated local archive; no crop-count or category quota',
                     'discovery_status':'historical_data','identity_basis':'Audited archive commodity identity'}
    inventory=ROOT/'Dataset/India Commodity Wise Mandi Dataset'
    names={text(p.stem) for p in inventory.glob('*.csv')}|set(crops)
    path=DAILY/'refresh_manifest.json'
    if path.exists():
        for part in json.loads(path.read_text(encoding='utf-8'))['partitions'].values():
            name=text(part['crop']);names.add(name)
            if part.get('records',0) and name not in crops:
                # import_recent revalidates raw hashes, cleans records and keeps
                # crop/market/variety/grade/source identities separate.
                crops[name]={'crop':name,'category':CROP_CATEGORY.get(name,'Unclassified'),
                             'usable_records':0,'daily_eligible_series':0,'last_date':part['date'],
                             'discovery_status':'accepted_source','identity_basis':'Accepted exact provider commodity/date/unit contract'}
    rows=[{'crop':name,'status':crops[name]['discovery_status'] if name in crops else 'discovered',
           'identity_basis':crops[name]['identity_basis'] if name in crops else 'Local source filename; not yet audited for forecasting'} for name in sorted(names)]
    return {'version':'dynamic-commodities-v1','ranking_source_sha256':sha(ranking) if ranking.exists() else None,
            'selection_rule':'All available validated archives and accepted exact-identity source commodities; series-level daily eligibility unchanged. No crop-count cap.',
            'discovery':rows,'discovered_count':len(rows),'historical_count':sum(r['status']=='historical_data' for r in rows),
            'crops':[crops[name] for name in sorted(crops)]}


def build():
    result=discover();write_json(OUT/'catalog.json',result)
    return result


if __name__=='__main__':
    result=build();print(json.dumps({'discovered':result['discovered_count'],'historical':result['historical_count'],'operational_catalog':len(result['crops'])}))
