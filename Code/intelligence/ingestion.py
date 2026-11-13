"""Budgeted paginated data.gov.in collection; immutable accepted crop-day vintages."""
from datetime import timedelta
import hashlib
import json
import math
import time
import requests
from urllib3.exceptions import HTTPError as TransportError
from Code.candidates.datagov_key_check import BASE, load_key
from Code.daily.dataset import ROOT, OUT, write_json, sha
from Code.daily.policy import now_ist, text
from Code.daily.refresh import RAW

ALIASES={'cucumber':'Cucumbar(Kheera)','common paddy':'Paddy(Dhan)(Common)',
         'paddy(common)':'Paddy(Dhan)(Common)','green ginger':'Ginger(Green)',
         'bhindi':'Bhindi(Ladies Finger)','radish':'Raddish'}
IDENTITY=['State','District','Market','Variety','Grade','Arrival_Date','Commodity']
SOURCE_NAMES={'Paddy(Dhan)(Common)':'Paddy(Common)'}


class BudgetExceeded(ValueError): pass
class ProviderFailure(ValueError): pass


def crop_name(value):
    value=text(value)
    return ALIASES.get(value.casefold(),value)


def validate_record(row,crop,day):
    if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip() for k in IDENTITY):
        raise ValueError('Missing market identity')
    if crop_name(row['Commodity'])!=crop or row['Arrival_Date']!=day.strftime('%d/%m/%Y'):
        raise ValueError('Provider did not respect commodity/date filters')
    try:
        lo,hi,price=[float(row[k]) for k in ('Min_Price','Max_Price','Modal_Price')]
    except (KeyError,TypeError,ValueError):
        raise ValueError('Invalid source price') from None
    # Preserve source anomalies for the existing cleaning rules; do not fabricate corrections.
    if not all(math.isfinite(v) for v in (lo,hi,price)):
        raise ValueError('Nonfinite source price')
    if row.get('Price_Unit') not in (None,'Rs/Quintal','INR/quintal'):
        raise ValueError('Unrecognized source price unit')
    return row


class Client:
    def __init__(self, budget, byte_budget, ledger, fetch=None, sleep=time.sleep, page_size=1000):
        if budget<1 or byte_budget<1: raise ValueError('Positive budgets required')
        self.budget,self.byte_budget,self.ledger=budget,byte_budget,ledger
        self.fetch,self.sleep,self.page_size=fetch,sleep,page_size
        self.session=requests.Session()
        self.key=load_key(ROOT) if fetch is None else None
        if fetch is None and not self.key: raise ProviderFailure('Missing configured data.gov.in credential')
        self.usage=json.loads(ledger.read_text()) if ledger.exists() else {'calls':0,'bytes':0,'retries':0}
        pause=OUT/'phase2_rate_limit.json'
        if fetch is None and pause.exists():
            deadline=json.loads(pause.read_text()).get('until')
            if deadline and now_ist().isoformat()<deadline:raise ProviderFailure('Provider rate-limit cooldown is active')

    def save(self):
        self.usage['updated_at']=now_ist().isoformat();write_json(self.ledger,self.usage)

    def page(self,crop,day,offset):
        for attempt in range(3):
            if self.usage['calls']>=self.budget or self.usage['bytes']>=self.byte_budget:
                raise BudgetExceeded('Request/download budget exhausted; accepted partitions retained')
            self.usage['calls']+=1;self.usage['last_request']={'crop':crop,'date':str(day),'offset':offset};self.save()
            try:
                if self.fetch:
                    body=self.fetch(crop,day,offset,self.page_size)
                    size=len(json.dumps(body).encode())
                    self.usage['bytes']+=size;self.save()
                else:
                    params={'api-key':self.key,'format':'json','limit':self.page_size,'offset':offset,
                            'filters[Commodity]':SOURCE_NAMES.get(crop,crop),'filters[Arrival_Date]':day.strftime('%d/%m/%Y')}
                    with self.session.get(BASE,params=params,timeout=(5,12),stream=True,headers={'User-Agent':'curl/8.0'}) as response:
                        if response.status_code==429:
                            self.usage['rate_limited']=True;self.usage['retry_after']=response.headers.get('Retry-After');self.save()
                            try:seconds=max(60,int(response.headers.get('Retry-After','3600')))
                            except ValueError:seconds=3600
                            write_json(OUT/'phase2_rate_limit.json',{'until':(now_ist()+timedelta(seconds=seconds)).isoformat(),'reason':'HTTP 429'})
                            raise ProviderFailure('Provider rate limit; accepted data retained, defer collection')
                        if response.status_code>=500:
                            raise requests.ConnectionError('Transient provider status')
                        if response.status_code!=200: raise ProviderFailure(f'Provider HTTP {response.status_code}')
                        parts=[]
                        while True:
                            remaining=self.byte_budget-self.usage['bytes']
                            if remaining<=0:raise BudgetExceeded('Download budget exhausted')
                            chunk=response.raw.read(min(65536,remaining),decode_content=True)
                            if not chunk:break
                            self.usage['bytes']+=len(chunk);self.save();parts.append(chunk)
                        body=json.loads(b''.join(parts))
                if self.usage['bytes']>self.byte_budget: raise BudgetExceeded('Download budget exhausted')
                if not isinstance(body,dict) or not isinstance(body.get('records'),list) or isinstance(body.get('total'),bool) or not str(body.get('total','')).isdigit():
                    raise ValueError('Invalid provider pagination metadata')
                # Conservative spacing after observed provider throttling. The
                # source does not publish a stable per-key request allowance.
                self.sleep(2.0)
                return body
            except (requests.RequestException,TransportError,json.JSONDecodeError) as exc:
                self.usage['last_error']=type(exc).__name__;self.save()
                if attempt==2: raise ProviderFailure('Provider unavailable after three bounded attempts') from None
                self.usage['retries']+=1;self.save();self.sleep(2**attempt)

    def partition(self,crop,day):
        # Two complete, independently paginated passes reject changing or repeated pages.
        def scan():
            rows=[];expected=None;offset=0;seen_pages=set()
            while True:
                body=self.page(crop,day,offset);total=int(body['total']);page=body['records']
                if expected is None: expected=total
                if total!=expected: raise ValueError('Provider total changed during pagination')
                if len(page)>self.page_size or (not page and offset<total): raise ValueError('Truncated pagination')
                page_hash=hashlib.sha256(json.dumps(page,sort_keys=True).encode()).hexdigest()
                if page and page_hash in seen_pages:raise ValueError('Repeated page: provider ignored pagination')
                seen_pages.add(page_hash)
                rows.extend(validate_record(r,crop,day) for r in page)
                if len(rows)>=total: break
                offset+=len(page)
            serialized=[json.dumps(r,sort_keys=True,ensure_ascii=False) for r in rows]
            if len(rows)!=expected or len(set(serialized))!=expected: raise ValueError('Duplicate pages or incomplete crop-day')
            # Conflicting identity values are source anomalies, not incomplete
            # downloads. Existing cleaning excludes them without losing the day.
            return rows,hashlib.sha256('\n'.join(sorted(serialized)).encode()).hexdigest()
        rows,first=scan();_,second=scan()
        if first!=second: raise ValueError('Repeated complete responses disagree')
        return rows,first


def collect(start,end,crops,budget=280,byte_budget=50_000_000,fetch=None,recheck=True,scope=None,sleep=time.sleep):
    if start>end or end>now_ist().date(): raise ValueError('Invalid collection dates')
    crops=[crop_name(c) for c in crops]
    manifest_path=OUT/'refresh_manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'partitions':{}}
    # A daily scope can recheck late observations; backfill scope resumes accepted dates.
    scope=scope or f'{start}:{end}:{now_ist().date()}:{recheck}'
    sid=hashlib.sha256(json.dumps([scope,crops,budget,byte_budget]).encode()).hexdigest()[:20]
    try:client=Client(budget,byte_budget,OUT/'phase2_usage'/f'{sid}.json',fetch=fetch,sleep=sleep)
    except ProviderFailure as exc:
        return {'status':'partial_provider_failure','calls':0,'usage':{},'new_records':0,'accepted':0,'errors':[{'reason':str(exc)}]}
    before=client.usage['calls'];accepted=new_records=0;failures=[]
    verified=client.usage.setdefault('verified',{})
    span=(end-start).days+1
    # Backfills establish the oldest boundary first, then fill newest-first.
    # This preserves the one-year span test under a bounded/resumable budget.
    offsets=([span-1]+list(range(span-1))) if not recheck else range(span)
    for offset in offsets:
        day=end-timedelta(days=offset)
        for crop in crops:
            key=f'{crop}|{day}';held=manifest['partitions'].get(key)
            if held:
                path=ROOT/held['path']
                if not path.exists() or sha(path)!=held['file_sha256']: raise ValueError('Accepted partition was modified')
                if not recheck or verified.get(key)==held['file_sha256']:continue
            try:
                rows,fingerprint=client.partition(crop,day)
            except BudgetExceeded:
                client.save()
                return {'status':'partial_budget','calls':client.usage['calls']-before,'usage':client.usage,'new_records':new_records,'accepted':accepted,'errors':failures}
            except (ProviderFailure,ValueError) as exc:
                failures.append({'crop':crop,'date':str(day),'reason':str(exc)})
                # An unavailable source should not burn an entire multi-year budget.
                if isinstance(exc,ProviderFailure):
                    return {'status':'partial_provider_failure','calls':client.usage['calls']-before,'usage':client.usage,'new_records':new_records,'accepted':accepted,'errors':failures}
                continue
            if held and json.loads((ROOT/held['path']).read_text(encoding='utf-8'))['double_fetch_content_sha256']==fingerprint:
                verified[key]=held['file_sha256'];client.save();continue
            old_rows=json.loads((ROOT/held['path']).read_text(encoding='utf-8'))['records'] if held else []
            old_content={json.dumps(r,sort_keys=True) for r in old_rows}
            inserted=sum(json.dumps(r,sort_keys=True) not in old_content for r in rows)
            stamp=now_ist().isoformat()
            path=RAW/hashlib.sha256(crop.encode()).hexdigest()[:12]/f'{day}-{fingerprint[:12]}-p2-{hashlib.sha256(stamp.encode()).hexdigest()[:8]}.json'
            write_json(path,{'records':rows,'retrieved_at':stamp,'commodity':crop,'date':str(day),'source':BASE,
                             'price_unit':'INR/quintal','unit_basis':'AGMARKNET resource contract; no inferred conversion',
                             'double_fetch_content_sha256':fingerprint,'collector':'phase2-paginated-v1'})
            revisions=[*held.get('revisions',[]),{k:v for k,v in held.items() if k!='revisions'}] if held else []
            manifest['partitions'][key]={'path':str(path.relative_to(ROOT)),'file_sha256':sha(path),'revisions':revisions,'crop':crop,
                                        'date':str(day),'records':len(rows),'retrieved_at':stamp,'status':'accepted' if rows else 'empty_report_not_zero_price'}
            write_json(manifest_path,manifest)
            verified[key]=manifest['partitions'][key]['file_sha256'];client.save()
            accepted+=1;new_records+=inserted
    return {'status':'completed_with_errors' if failures else 'completed','calls':client.usage['calls']-before,
            'usage':client.usage,'new_records':new_records,'accepted':accepted,'errors':failures}
