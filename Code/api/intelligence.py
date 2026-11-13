from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from Code.intelligence import service as s
from Code.daily.policy import now_ist
from Code.api import daily
from functools import lru_cache
from datetime import date
from Code.intelligence import market_inventory as inventory

router=APIRouter(prefix='/api/v4',tags=['Market intelligence'])


class PublishedResult(BaseModel):
    dataset_version: str
    batch_id: str


class ReportedSeries(BaseModel):
    series_id: str
    crop: str
    variety: str
    grade: str
    source: str
    state: str
    district: str
    market: str
    observation_date: str | None
    last_observed_price: float
    predicted_price: float | None
    forecast_ready: bool
    status: str


class CropReport(ReportedSeries):
    recent_movement_rs: float | None


class MarketCrops(PublishedResult):
    rows: list[CropReport]
    total: int
    total_series: int
    crop_count: int
    forecast_series: int


class MarketChoice(BaseModel):
    series_id: str
    crop: str
    label: str
    price: float | None


class MarketPin(MarketChoice):
    id: int
    lat: float
    lng: float
    approximate: bool


class MarketMap(PublishedResult):
    points: list[MarketPin]
    unmapped: list[MarketChoice]
    unmapped_count: int
    bounds: tuple[float, float] | None
    states: list[str]
    state_options: list[dict[str, str]]
    selected_state_id: str


class TradeSummary(BaseModel):
    id: str
    buy_id: str
    sell_id: str
    buy_market: str
    sell_market: str
    net_margin: float
    adjusted_value: float
    freight: float
    quantity_q: float
    distance_km: float
    hours: float
    route_basis: str
    objective: str


class TradeOpportunity(TradeSummary):
    crop: str
    variety: str
    grade: str
    source: str
    handling: float


class MarketOpportunity(TradeOpportunity):
    comparison: str | None
    alternative: TradeSummary | None


class MarketOpportunities(PublishedResult):
    rows: list[MarketOpportunity]
    total: int


class NearbyMarket(ReportedSeries):
    coordinate: dict
    reported_crops: list[str]
    distance_km: float
    distance_kind: str
    distance_basis: str
    freight: float
    comparable_markets: int
    peer_median_price: float | None


class NearbyMarkets(PublishedResult):
    rows: list[NearbyMarket]
    radius_km: float
    total: int


class StorageOpportunity(TradeOpportunity):
    days: int
    storage: float
    loss_pct: float
    sale_price: float
    sale_revenue: float
    sale_kind: Literal['future_forecast', 'persistence_assumption', 'scenario']
    immediate_margin: float
    margin_difference: float
    adjusted_difference: float
    future_change: float


class StorageOpportunities(PublishedResult):
    rows: list[StorageOpportunity]
    total: int


@router.get('/market-intelligence')
def market_intelligence(crop:str,series_id:str,quantity:float=Query(100,gt=0,le=100000)):
    from Code.intelligence.market_context import detail
    pointer=daily.snapshot()[3]
    return bound(detail(crop,series_id,quantity),pointer)


@router.get('/market-environment')
def market_environment(crop:str,series_id:str):
    from Code.intelligence.market_context import resolve
    from Code.intelligence.environment import context
    pointer=daily.snapshot()[3]
    return bound(context(resolve(crop,series_id).get('coordinate'),fetch=True),pointer)


@router.get('/market-map', response_model=MarketMap)
def market_map(crop: str | None = None, state: str = '', search: str = Query('', max_length=100),
               basis: Literal['reported', 'forecast'] = 'reported'):
    pointer = daily.snapshot()[3]
    if crop:
        s.valid_crop(crop)
    return bound(inventory.map_inventory(pointer, crop, state, search, basis if crop else 'reported'), pointer)


@router.get('/regional-weather')
def regional_weather():
    from Code.intelligence.environment import regional_weather as samples
    return {'rows': samples()}


@router.get('/market-place')
def market_place(crop: str, series_id: str):
    from Code.intelligence.market_context import resolve, warehouse_options
    pointer = daily.snapshot()[3]
    market = resolve(crop, series_id)
    coordinate = market['coordinate']
    connections = []
    if coordinate:
        candidates = [(s.distance(coordinate, {'lat': n['latitude'], 'lng': n['longitude']}), n)
                      for n in s.nodes() if n['node_id'] != coordinate['node']]
        seen = set()
        for distance, node in sorted(candidates, key=lambda pair: pair[0]):
            position = node['latitude'], node['longitude']
            if distance < 1 or position in seen:
                continue
            if distance > s.CONFIG['market_context']['nearby_radius_km'] or len(connections) == 3:
                break
            seen.add(position)
            route = min(s.route_options(coordinate['node'], node['node_id']), key=lambda r: r['km'])
            connections.append({'name': node.get('market') or node['district'], **route})
    from Code.intelligence.states import NAMES, state_id
    return bound({'market': {**market, 'state_name': NAMES.get(state_id(market['state']), market['state'])},
                  'warehouses': warehouse_options(market, prefer_compatible=False),
                  'connections': connections}, pointer)


@router.get('/warehouses/{warehouse_id}/environment')
def warehouse_environment(warehouse_id: str):
    from Code.intelligence.environment import context
    from Code.intelligence.warehouse_context import facility
    warehouse = facility(warehouse_id)
    return context({'lat': warehouse['latitude'], 'lng': warehouse['longitude'],
                    'node': warehouse_id, 'precision': 'Reported facility reference'}, fetch=True)


@router.get('/market-crops', response_model=MarketCrops)
def market_crops(series_id: str, search: str = Query('', max_length=100),
                 sort: Literal['crop', 'latest', 'forecast'] = 'crop',
                 offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=50)):
    pointer = daily.snapshot()[3]
    return bound(inventory.inventory(series_id, pointer, search, sort, offset, limit), pointer)


@router.get('/market-opportunities', response_model=MarketOpportunities)
def market_opportunities(series_id: str, side: Literal['buy', 'sell'],
                         offset: int = Query(0, ge=0), limit: int = Query(3, ge=1, le=20)):
    from Code.intelligence.market_context import opportunities
    pointer = daily.snapshot()[3]
    rows = opportunities(series_id, side, pointer)
    return bound({'rows': rows[offset:offset + limit], 'total': len(rows)}, pointer)


def bound(result,pointer):
    if daily.snapshot()[3]['sha256']!=pointer['sha256']:
        raise HTTPException(503,'A new forecast batch was published. Refresh to use consistent data.')
    return {**result,'dataset_version':pointer['dataset_version'],'batch_id':pointer['sha256']}


@router.get('/coverage')
def coverage():
    path=daily.auxiliary_path('coverage',s.OUT/'phase2/coverage.json')
    if not path.exists():raise HTTPException(503,'Coverage audit not generated yet')
    result=s.json.loads(path.read_text(encoding='utf-8'))
    if result['dataset_version']!=daily.snapshot()[3]['dataset_version']:
        raise HTTPException(503,'Coverage is updating for the newly published batch. Refresh shortly.')
    if result['batch_target']!=str(now_ist().date()):
        result['forecast_count']=result['eligible_crop_count']=0
        for row in result['rows']:row.update(eligible_forecasts=0,reason='Expired forecast batch')
    return result


@router.get('/route')
def route(origin:str,destination:str,objective:Literal['shortest','fastest']='shortest'):
    from Code.intelligence.roads import geometry
    computed=geometry(origin,destination,objective)
    if computed:return {'geometry':computed}
    if origin==destination:
        return {'geometry':None}
    try:
        result=s.lg.route(origin,destination,objective)
    except HTTPException as exc:
        if exc.status_code not in (404, 503):
            raise
        return {'geometry':None}
    # Project route artifacts already store Leaflet order (latitude, longitude).
    return {'geometry': result.get('geometry')}


@router.get('/journey-path')
def journey_path(origin: str, destination: str, objective: Literal['shortest', 'fastest'] = 'shortest',
                 warehouse_id: str | None = None):
    from Code.intelligence import roads
    from Code.intelligence.warehouse_context import facility

    nodes = {row['node_id']: (row['latitude'], row['longitude']) for row in s.nodes()}
    if origin not in nodes or destination not in nodes or origin == destination:
        return {'geometry': None}
    if not warehouse_id:
        saved = route(origin, destination, objective)['geometry']
        if saved:
            return {'geometry': saved, 'source': 'Saved OpenStreetMap route'}
        return roads.local_geometry(nodes[origin], nodes[destination], objective)
    warehouse = facility(warehouse_id)
    return roads.local_geometry(nodes[origin], nodes[destination], objective,
                                (warehouse['latitude'], warehouse['longitude']))


@router.get('/route-conditions')
def route_conditions(origin: str, destination: str, objective: Literal['shortest', 'fastest', 'approximate', 'via_storage'],
                     warehouse_id: str | None = None):
    from concurrent.futures import ThreadPoolExecutor
    from Code.intelligence import environment, roads
    from Code.intelligence.warehouse_context import facility

    nodes = {row['node_id']: row for row in s.nodes()}
    if origin not in nodes or destination not in nodes:
        raise HTTPException(404, 'Route references unavailable')
    start, end = nodes[origin], nodes[destination]
    samples = [('Origin', start['latitude'], start['longitude'])]
    if objective == 'via_storage' and warehouse_id:
        stop = facility(warehouse_id)
        samples.append(('Storage stop', stop['latitude'], stop['longitude']))
    elif objective in ('shortest', 'fastest'):
        line = roads.geometry(origin, destination, objective)
        if not line:
            line = route(origin, destination, objective)['geometry']
        if line and len(line) > 2:
            lengths = [s.distance({'lat': a[0], 'lng': a[1]}, {'lat': b[0], 'lng': b[1]}) for a, b in zip(line, line[1:])]
            if sum(lengths) >= 100:
                target = sum(lengths) / 2
                for (a, b), length in zip(zip(line, line[1:]), lengths):
                    if length and target <= length:
                        fraction = target / length
                        samples.append(('Mid-route', a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction))
                        break
                    target -= length
    if destination != origin:
        samples.append(('Destination', end['latitude'], end['longitude']))

    def conditions(sample):
        name, lat, lng = sample
        return {'name': name, **environment.context({'lat': lat, 'lng': lng, 'precision': 'Route sample'}, fetch=True)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        return {'samples': list(pool.map(conditions, samples))}


@router.get('/weather')
def weather(series_id:str):
    from Code.api.decisions import weather_context
    price=daily.today(series_id)
    coordinate=s.market_coordinate(price)
    if coordinate and coordinate['node'].startswith(('G:','M:')):
        from Code.decision.weather_context import context
        import hashlib
        return {**context('georef_'+hashlib.sha256(coordinate['node'].encode()).hexdigest()[:20],coordinate['lat'],coordinate['lng']),
                'coverage':coordinate['precision']+'; outdoor forecast, not a market-site measurement','used_in_price_model':False}
    return weather_context(series_id)


@router.get('/supply-context')
def supply_context(crop:str,state:str):
    s.valid_crop(crop)
    if crop not in ('Onion','Potato','Wheat'):
        return {'arrivals':None,'production':None,'note':'No integrated arrivals or production context for this crop.'}
    from Code.api.main import weekly,production
    frame=weekly()
    frame=frame[(frame.crop==crop)&(frame.state==state)].sort_values('week_start')
    arrivals=None if frame.empty else {'tonnes':float(frame.iloc[-1].arrivals_tonnes_sum),'week':str(frame.iloc[-1].week_start)[:10],'basis':'Historical reported arrivals; not current supply'}
    prod=production()
    prod=prod[(prod.crop==crop)&(prod.apy_state==state)&(prod.source_apy_year<='2018-2019')]
    if len(prod):
        prod=prod[prod.source_apy_year==prod.source_apy_year.max()].drop_duplicates(['apy_district','source_apy_year'])
    return {'arrivals':arrivals,'production':None if prod.empty else {'tonnes':float(prod.production_tonnes.sum()),'year':str(prod.source_apy_year.max()),'basis':'Historical district production context, not current measured supply'},
            'note':'Context only; no price adjustment. Historical publication availability is not reconstructed.'}


@router.get('/overview')
def overview():
    manifest,_,_,pointer=daily.snapshot()
    state=s.OUT/'phase2'
    success_path=daily.auxiliary_path('last_success',state/'last_success.json')
    success=s.json.loads(success_path.read_text(encoding='utf-8')) if success_path.exists() else None
    status=s.json.loads((state/'status.json').read_text(encoding='utf-8')) if (state/'status.json').exists() else None
    refresh={'last_success':success.get('successful_publication_at') if success else None,'latest_observation':success.get('latest_source_observation') if success else None,'status':status.get('status') if status else 'not_run'}
    pause=s.DAILY/'phase2_rate_limit.json'
    refresh['source_waiting']=pause.exists() and s.json.loads(pause.read_text()).get('until','')>now_ist().isoformat()
    return bound({'catalog': manifest['catalog'], 'freshness': daily.freshness(), 'refresh':refresh,'config': s.CONFIG, 'date': str(now_ist().date()),
            'states': sorted({r['state'] for r in s.nodes()})},pointer)


@router.get('/markets')
def markets(crop: str|None=None, state: str|None=None, district: str|None=None, search: str=Query('',max_length=100), recent: bool=False,
            min_price: float=Query(0,ge=0), max_price: float=Query(1000000,ge=0), offset: int=Query(0,ge=0),limit: int=Query(100,ge=1,le=200)):
    pointer=daily.snapshot()[3]
    if crop:
        s.valid_crop(crop)
    return bound(inventory.discovery(pointer,crop,state,district,search,recent,min_price,max_price,offset,limit),pointer)


@router.get('/market-history')
def history(crop:str,series_id:str):
    s.valid_crop(crop)
    _,registry,_,_=daily.snapshot()
    match=registry[registry.series_id==series_id]
    if not match.empty:
        if match.iloc[0].crop!=crop: raise HTTPException(422,'Crop and series mismatch')
        return daily.history(series_id,60)
    entry=next(r for r in s.catalog()['crops'] if r['crop']==crop)
    if not entry.get('storage'):raise HTTPException(404,'No validated history for this market series')
    path=s.DAILY/entry['storage']/'observations.parquet'
    frame=s.pd.read_parquet(path,filters=[('series_id','==',series_id)]).sort_values('date').tail(60)
    if frame.empty: raise HTTPException(404,'Market history unavailable')
    return {'kind':'observed','points':s.lg._records(frame[['date','price']].assign(date=frame.date.dt.strftime('%Y-%m-%d')))}


@router.get('/warehouses')
def warehouses(crop:str|None=None,state:str|None=None,kind:str|None=None,min_free_t:float=Query(0,ge=0),max_charge:float=Query(100,ge=0),market_search:str=Query('',max_length=100)):
    if crop: s.valid_crop(crop)
    rows=s.warehouses()
    states=sorted({r['region'] for r in rows})
    if market_search.strip():
        from Code.intelligence.warehouse_context import _mapped
        term = inventory.text(market_search).casefold()
        points = [point for key, point in _mapped(daily._signature(),s.config_signature()) if term in key[2]]
        radius = s.CONFIG['market_context']['nearby_radius_km']
        rows = [r for r in rows if any(s.distance(point, {'lat':r['latitude'],'lng':r['longitude']}) <= radius for point in points)]
    return {'rows':[r for r in rows if (not crop or crop in r['supported_crops']) and (not state or r['region']==state)
                    and (not kind or r['storage_class']==kind) and r['free_t']>=min_free_t and r['rs_q_day']<=max_charge],
            'states':states, 'compatibility':s.storage_catalog()}


@lru_cache(maxsize=12)
def _planned_strategies(batch_id, minute, revision, args, transport, evidence=None):
    from Code.intelligence.explanations import quality_rows, quality_snapshot
    token = quality_snapshot.set(quality_rows())
    try:
        return s.strategies(*args, integrated=True, **dict(transport))
    finally:
        quality_snapshot.reset(token)


@router.get('/strategies')
def strategies(crop:str|None=None,state:str|None=None,quantity:float=Query(100,gt=0,le=100000),vehicle:str='Medium truck',buy_id:str|None=None,sell_id:str|None=None,mode:Literal['auto','both','intrastate','interstate']='both',selected_id:str|None=None,plan:bool=False,warehouse_id:str|None=None,purchase_date:date|None=None,
               handling:float|None=Query(None,ge=0,le=1000),loss:float|None=Query(None,ge=0,le=50),rs_km:float|None=Query(None,gt=0,le=500),capacity_q:float|None=Query(None,gt=0,le=500),
               toll_rs_trip:float|None=Query(None,ge=0,le=50000),congestion_pct:float=Query(0,ge=0,le=200),loading_minutes:float=Query(0,ge=0,le=720),delay_rs_hour:float=Query(0,ge=0,le=5000)):
    if vehicle not in s.CONFIG['vehicles']: raise HTTPException(422,'Choose a supported truck')
    if purchase_date is not None and not 0 <= (purchase_date - now_ist().date()).days <= s.CONFIG['planning']['horizon_days']:
        raise HTTPException(422, 'Choose a purchase date within the current planning window.')
    if purchase_date is not None:
        plan = True
    args = (crop,state,quantity,vehicle,buy_id,sell_id,mode,True,selected_id,handling,loss,rs_km,capacity_q)
    transport = dict(toll_rs_trip=toll_rs_trip,congestion_pct=congestion_pct,loading_minutes=loading_minutes,
                     delay_rs_hour=delay_rs_hour,warehouse_id=warehouse_id,purchase_date=purchase_date)
    if plan:
        from Code.intelligence.roads import path_revision
        pointer = daily.snapshot()[3]
        held = daily.serving() or {}
        evidence = (held.get('auxiliary', {}).get('quality'), s.config_signature())
        result = _planned_strategies(pointer['sha256'], now_ist().replace(second=0, microsecond=0),
                                     path_revision(), args, tuple(transport.items()), evidence)
    else:
        result = s.strategies(*args, **transport)
    if daily.snapshot()[3]['sha256']!=result['batch_id']:
        raise HTTPException(503,'A new forecast batch was published. Refresh the opportunities to use its consistent filters.')
    return {**result,'ranking':'Net margin screened by historical error, recent price movement, data age and route evidence. Similar adjusted values favour supported roads, shorter journeys and fewer trips. Deductions are comparison assumptions, not extra operating expenses or confidence intervals.',
            'empty_reason':'No compatible, mapped current forecasts match these filters. Historical data is available in Markets.' if not result['rows'] else None}


@router.get('/discovery')
def discovery():
    result=s.strategies(details=True)
    catalog=s.catalog()
    if daily.snapshot()[3]['sha256']!=result['batch_id']:raise HTTPException(503,'Commodity discovery is updating. Refresh shortly.')
    forecast_ready=set(result['forecast_ready_crops']);strategy_ready=set(result['strategy_ready_crops'])
    return {'dataset_version':result['dataset_version'],'batch_id':result['batch_id'],
            'discovered_count':catalog.get('discovered_count',len(catalog['crops'])),
            'historical_count':catalog.get('historical_count',len(catalog['crops'])),
            'forecast_ready_count':len(forecast_ready),'strategy_ready_count':len(strategy_ready),
            'forecast_ready_crops':result['forecast_ready_crops'],'strategy_ready_crops':result['strategy_ready_crops'],
            'crops':[{**r,'historical_data':r['status'] in ('historical_data','accepted_source'),'forecast_ready':r['crop'] in forecast_ready,'strategy_ready':r['crop'] in strategy_ready}
                     for r in catalog.get('discovery',[{'crop':r['crop'],'status':'historical_data'} for r in catalog['crops']])]}


@router.get('/mode-availability')
def mode_availability():
    from Code.intelligence.availability import audit
    pointer=daily.snapshot()[3]
    return bound({'rows':audit()},pointer)


class Scenario(BaseModel):
    buy_id:str
    sell_id:str
    quantity:float=Field(100,gt=0,le=100000)
    vehicle:Literal['Light truck','Medium truck','Heavy truck']='Medium truck'
    handling:float=Field(18,ge=0,le=1000)
    loss:float=Field(1,ge=0,le=50)
    days:int=Field(0,ge=0,le=90)
    warehouse_id:str|None=None
    route_index:int=Field(0,ge=0,le=2)
    future_change:float=Field(0,ge=-50,le=100)
    rs_km:float|None=Field(None,gt=0,le=500)
    capacity_q:float|None=Field(None,gt=0,le=500)
    future_mode:Literal['scenario','forecast']='scenario'
    batch_id: str | None = None
    toll_rs_trip: float | None = Field(None, ge=0, le=50000)
    congestion_pct: float = Field(0, ge=0, le=200)
    loading_minutes: float = Field(0, ge=0, le=720)
    delay_rs_hour: float = Field(0, ge=0, le=5000)


def scenario_pointer(batch_id):
    pointer = daily.snapshot()[3]
    if batch_id and pointer['sha256'] != batch_id:
        raise HTTPException(503, 'The selected forecasts have changed. Refresh before running this comparison.')
    return pointer


class StorageLoad(BaseModel):
    crop: str = Field(min_length=1, max_length=100)
    quantity_q: float = Field(gt=0, le=100000)
    days: int = Field(ge=1, le=90)


class AllocationPreview(BaseModel):
    loads: list[StorageLoad] = Field(min_length=1, max_length=20)


class CheckedLoad(StorageLoad):
    compatible: bool
    duration_ok: bool
    fits_alone: bool
    storage_charge: float | None


class AllocationResult(BaseModel):
    requested_t: float
    available_t: float
    fits_together: bool
    feasible: bool
    rows: list[CheckedLoad]


@router.post('/warehouses/{warehouse_id}/allocation', response_model=AllocationResult)
def warehouse_allocation(warehouse_id: str, request: AllocationPreview):
    from Code.intelligence.warehouse_context import facility
    return s.allocation(facility(warehouse_id), [load.model_dump() for load in request.loads])


@router.get('/warehouses/{warehouse_id}/nearby-markets', response_model=NearbyMarkets)
def warehouse_nearby(warehouse_id: str, crop: str | None = None, quantity: float = Query(100, gt=0, le=100000)):
    from Code.intelligence.warehouse_context import facility, nearby
    pointer = daily.snapshot()[3]
    return bound(nearby(facility(warehouse_id), pointer, quantity, crop), pointer)


@router.get('/warehouses/{warehouse_id}/opportunities', response_model=StorageOpportunities)
def warehouse_opportunities(warehouse_id: str, crop: str | None = None, series_id: str | None = None,
                            quantity: float = Query(100, gt=0, le=100000),
                            future_change: float | None = Query(None, ge=-50, le=100),
                            offset: int = Query(0, ge=0), limit: int = Query(4, ge=1, le=20)):
    from Code.intelligence.warehouse_context import facility, opportunities
    pointer = daily.snapshot()[3]
    warehouse = facility(warehouse_id)
    request = Scenario(buy_id='', sell_id='', quantity=quantity, handling=s.CONFIG['handling_rs_q'],
                       future_mode='forecast' if future_change is None else 'scenario',
                       future_change=future_change if future_change is not None else 0)
    rows = opportunities(warehouse, request, crop, series_id)
    return bound({'rows': rows[offset:offset + limit], 'total': len(rows)}, pointer)


@router.post('/scenario')
def scenario(req:Scenario):
    pointer = scenario_pointer(req.batch_id)
    prices={r['series_id']:{**r,'predicted_price':r['predicted_modal_price'],'coordinate':s.market_coordinate(r)} for r in s.current_prices()}
    if req.buy_id not in prices or req.sell_id not in prices: raise HTTPException(422,'Current forecasts are unavailable for the selected markets')
    if req.buy_id==req.sell_id: raise HTTPException(422,'Choose different buying and selling markets')
    try:
        from Code.intelligence.storage_decisions import calculate
        return bound(calculate(prices[req.buy_id],prices[req.sell_id],req), pointer)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get('/future-price')
def future_price(series_id:str,horizon:int=Query(7)):
    from Code.intelligence.future import forecast
    try:return forecast(daily.today(series_id),horizon)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.post('/storage-options')
def storage_options(req:Scenario):
    from Code.intelligence.storage_decisions import compare
    pointer = scenario_pointer(req.batch_id)
    try:return bound(compare(req), pointer)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
