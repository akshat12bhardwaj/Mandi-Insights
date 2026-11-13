"""Honest observed/forecast boundaries and deterministic logistics scenarios."""
import hashlib
import json
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import pandas as pd
from fastapi import HTTPException
from Code.api import daily, logistics as lg
from Code.daily.dataset import OUT as DAILY
from Code.daily.policy import now_ist
from .build import OUT

CONFIG = json.loads(Path(__file__).with_name('config.json').read_text())


def catalog():
    pointer=DAILY/'release.json'
    if pointer.exists():
        # Read the catalog inside the successful release, never a mutable draft
        # belonging to a refresh that may subsequently fail.
        return daily.snapshot()[0]['catalog']
    return json.loads((OUT / 'catalog.json').read_text())


def valid_crop(crop):
    if crop not in {r['crop'] for r in catalog()['crops']}:
        raise HTTPException(422, 'Choose a supported crop')


@lru_cache(maxsize=2)
def _nodes(signature):
    rows=lg.routing_nodes().to_dict('records')
    path=OUT/'phase2/district_references.json'
    if path.exists():rows+=json.loads(path.read_text(encoding='utf-8'))['rows']
    market=OUT/'phase3/market_locations.json'
    if market.exists():rows+=json.loads(market.read_text(encoding='utf-8'))['accepted']
    local=OUT/'phase5/locality_references.json'
    if local.exists():rows+=json.loads(local.read_text(encoding='utf-8'))['rows']
    return rows


def nodes():
    path=OUT/'phase2/district_references.json'
    market=OUT/'phase3/market_locations.json'
    local=OUT/'phase5/locality_references.json'
    return _nodes((path.stat().st_mtime_ns if path.exists() else None,market.stat().st_mtime_ns if market.exists() else None,local.stat().st_mtime_ns if local.exists() else None))


def coordinate(state, district):
    from .states import state_id
    from Code.daily.policy import text
    region = state_id(state)
    match = [n for n in nodes() if not n.get('market_key') and n['node_id'].startswith(('D:','G:'))
             and (n['state'].casefold() == state.casefold() or (region and state_id(n['state']) == region))
             and text(n['district']).casefold() == text(district).casefold()]
    return ({'lat': match[0]['latitude'], 'lng': match[0]['longitude'], 'node': match[0]['node_id'],
             'precision': 'Approximate locality reference (GeoNames)' if match[0].get('verification')=='geocoded_locality' else 'Approximate district reference'} if len(match) == 1 else None)


def market_coordinate(row):
    match=next((n for n in nodes() if n.get('market_key')=='|'.join(row[k] for k in ('state','district','market'))),None)
    return {'lat':match['latitude'],'lng':match['longitude'],'node':match['node_id'],'precision':match['precision']} if match else coordinate(row['state'],row['district'])


def distance(a, b):
    r1, r2 = math.radians(a['lat']), math.radians(b['lat'])
    v = math.sin((r2-r1)/2)**2 + math.cos(r1)*math.cos(r2)*math.sin(math.radians(b['lng']-a['lng'])/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(v)))


@lru_cache(maxsize=24)
def archive(crop):
    entry = next(r for r in catalog()['crops'] if r['crop'] == crop)
    if not entry.get('storage'):return []
    path = DAILY / entry['storage']
    series = pd.read_parquet(path / 'series.parquet')
    hist = pd.read_parquet(path / 'observations.parquet', columns=['series_id', 'date', 'price'])
    last = hist.sort_values('date').groupby('series_id', observed=True).tail(1)
    merged = series.merge(last[['series_id', 'price']], on='series_id')
    return [{**r, 'crop': crop, 'predicted_price': None, 'last_observed_price': r['price'],
             'observation_date': r['last_date'], 'coordinate': coordinate(r['state'], r['district']),
             'status': 'Historical observations', 'arrivals': None} for r in lg._records(merged)]


def current_prices():
    _, _, batch, pointer = daily.snapshot()
    if pointer['target_date'] != str(now_ist().date()) or pd.Timestamp(pointer['issue']) > pd.Timestamp(now_ist()):
        return []
    with batch.connect() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM predictions WHERE price IS NOT NULL')]


def markets(crop):
    valid_crop(crop)
    recent = []
    for r in current_prices():
        if r['crop'] != crop:
            continue
        recent.append({**r, 'predicted_price': r['predicted_modal_price'],
                       'observation_date': r['last_observation_date'], 'coordinate': market_coordinate(r),
                       'status': 'Estimated today', 'arrivals': None})
    # Archives and recent sources stay separate; no unsupported identity bridge.
    return recent + archive(crop)


def storage_class(crop):
    entry=next(r for r in catalog()['crops'] if r['crop']==crop)
    return _crop_storage(crop,entry['category'])


def _crop_storage(crop,category):
    if crop in ('Onion', 'Garlic'):
        return 'ventilated'
    if category in ('Vegetables', 'Fruits'):
        return 'cold'
    if category in ('Cereals and grains', 'Pulses and legumes', 'Oilseeds') or crop in ('Dry Chillies', 'Black pepper'):
        return 'dry'
    return 'unsupported'


def storage_catalog():
    requirements = {
        'dry': 'Keep dry and protected from moisture. Use ventilation and pest control appropriate to the crop.',
        'ventilated': 'Cure and sort bulbs before storage. Keep them dry with continuous airflow.',
        'cold': 'Verify the crop-specific temperature and humidity settings, airflow and chilling sensitivity.',
        'unsupported': 'Crop requirements or a matching project storage class are unavailable.',
    }
    return [{'crop': row['crop'], 'category': row['category'], 'storage_class': kind,
             'requirements': requirements[kind]}
            for row in catalog()['crops'] for kind in [_crop_storage(row['crop'], row['category'])]]


def allocation(warehouse, loads):
    """Preview concurrent loads against one facility-wide pool, in quintals."""
    rows = []
    quantities = [Decimal(str(load['quantity_q'])) for load in loads]
    total_q = sum(quantities)
    available_q = Decimal(str(warehouse['free_t'])) * 10
    for load, quantity in zip(loads, quantities):
        supported = load['crop'] in warehouse['supported_crops']
        duration_ok = 0 < load['days'] <= warehouse['max_days']
        rows.append({**load, 'compatible': supported, 'duration_ok': duration_ok,
                     'fits_alone': quantity <= available_q,
                     'storage_charge': round(load['quantity_q'] * load['days'] * warehouse['rs_q_day'], 2)
                     if supported and duration_ok else None})
    return {'requested_t': float(total_q / 10), 'available_t': warehouse['free_t'],
            'fits_together': total_q <= available_q,
            'feasible': total_q <= available_q and
                        all(row['compatible'] and row['duration_ok'] for row in rows),
            'rows': rows}


def simulated_facility(row, day):
    seed = int(hashlib.sha256(row['warehouse_id'].encode()).hexdigest()[:12], 16)
    # Stable classification is a simulation, never a facility certification.
    kind = 'cold' if row['facility_type'] == 'cold_storage' else ('ventilated' if seed % 4 == 0 else 'dry')
    cfg = CONFIG['storage'][kind]
    reported = row.get('capacity_total_t')
    reported = reported if isinstance(reported,(int,float)) and math.isfinite(reported) and reported>0 else None
    total = float(reported or cfg['capacity_t'] * (0.5 + (seed % 6) / 5))
    week = pd.Timestamp(day).toordinal() // 7
    occupancy = max(30, min(95, [35, 50, 65, 75, 90][seed % 5] + ((week + seed) % 5 - 2)))
    occupied = round(total * occupancy / 100, 2)
    near = min(nodes(), key=lambda n: distance({'lat': row['latitude'], 'lng': row['longitude']}, {'lat': n['latitude'], 'lng': n['longitude']}))
    return {**row, 'storage_class': kind, 'class_basis': 'Simulated crop suitability',
            'region': near['state'], 'district_reference': near['district'], 'region_basis': 'Nearest project reference, approximate',
            'total_t': total, 'occupied_t': occupied, 'free_t': round(total-occupied, 2), 'occupancy_pct': occupancy,
            'capacity_basis': 'Reported nominal capacity' if reported else 'Simulated capacity',
            'availability_basis': 'Simulated availability', 'rs_q_day': cfg['rs_q_day'], 'max_days': cfg['max_days'],
            'supported_crops': [r['crop'] for r in catalog()['crops'] if _crop_storage(r['crop'],r['category']) == kind],
            'status': 'Nearly full' if occupancy >= 85 else 'Limited availability' if occupancy >= 70 else 'Good availability'}


def warehouses():
    version = daily.snapshot()[3]['dataset_version'] if (DAILY/'release.json').exists() else None
    return _warehouses(str(now_ist().date()),config_signature(),version)


@lru_cache(maxsize=2)
def _warehouses(day,signature,dataset_version):
    table = lg.warehouses()
    if table is None:
        return []
    return [simulated_facility(r,day) for r in lg._records(table.drop_duplicates('warehouse_id'))]


def route_options(origin, destination):
    file=OUT/'phase3/roads_v1/routes.parquet'
    return _route_options(origin,destination,file.stat().st_mtime_ns if file.exists() else None)


@lru_cache(maxsize=4096)
def _route_options(origin, destination,signature):
    from . import roads
    computed=roads.saved(origin,destination)
    if computed:
        return [{'objective':r['objective'],'km':r['road_km']+CONFIG['access_km_per_endpoint']*2,
                 'hours':r['road_hours']+CONFIG['access_km_per_endpoint']*2/25,'basis':'Directed OSM road path + assumed endpoint access',
                 'origin':origin,'destination':destination} for r in computed]
    a, b = next(n for n in nodes() if n['node_id'] == origin), next(n for n in nodes() if n['node_id'] == destination)
    od = lg.od()
    paths = [] if od is None else od[(od.origin_id == origin) & (od.dest_id == destination) & (od.status == 'ok')].to_dict('records')
    if paths:
        return [{'objective': r['objective'], 'km': float(r['road_distance_km']) + CONFIG['access_km_per_endpoint']*2,
                 'hours': float(r['travel_time_h']) + CONFIG['access_km_per_endpoint']*2/25,
                 'basis': 'Saved OSM road route + assumed endpoint access', 'origin': origin, 'destination': destination} for r in paths]
    km = distance({'lat': a['latitude'], 'lng': a['longitude']}, {'lat': b['latitude'], 'lng': b['longitude']}) * CONFIG['road_detour_factor'] + CONFIG['access_km_per_endpoint']*2
    return [{'objective': 'approximate', 'km': km, 'hours': km/35, 'basis': 'Approximate distance scenario', 'origin': origin, 'destination': destination}]


route_options.cache_clear=_route_options.cache_clear


def calculate(buy, sell, quantity, vehicle, handling, loss, days=0, warehouse=None, route_index=0, future_change=0, rs_km=None, capacity_q=None,
              toll_rs_trip=None, congestion_pct=0, loading_minutes=0, delay_rs_hour=0, planned=False):
    a, b = buy['coordinate'], sell['coordinate']
    if not a or not b:
        raise ValueError('Both markets need a mapped reference')
    if any(buy[k] != sell[k] for k in ('crop', 'variety', 'grade', 'source')):
        raise ValueError('Choose the same crop, variety, grade and source')
    if days and (not warehouse or not allocation(warehouse, [
            {'crop': buy['crop'], 'quantity_q': quantity, 'days': days}])['feasible']):
        raise ValueError('Choose compatible storage with enough space and a suitable duration')
    truck = dict(CONFIG['vehicles'][vehicle])
    if rs_km is not None: truck['rs_km']=rs_km
    if capacity_q is not None: truck['capacity_q']=capacity_q
    trips = math.ceil(quantity / truck['capacity_q'])
    routes = [dict(r) for r in route_options(a['node'], b['node'])]
    if days:
        w = {'lat': warehouse['latitude'], 'lng': warehouse['longitude']}
        km = (distance(a,w)+distance(w,b))*CONFIG['road_detour_factor']+CONFIG['access_km_per_endpoint']*2
        hours=km/35
        inbound_hours=(distance(a,w)*CONFIG['road_detour_factor']+CONFIG['access_km_per_endpoint'])/35
        links=lg.node_warehouse()
        legs=[]
        if links is not None and warehouse.get('warehouse_id'):
            for endpoint in (a['node'],b['node']):
                match=links[(links.node_id==endpoint)&(links.warehouse_id==warehouse['warehouse_id'])]
                if len(match):legs.append(match.iloc[0])
        basis='Approximate market–warehouse–market distance scenario'
        if len(legs)==2:
            km=sum(float(r.road_distance_km) for r in legs)+CONFIG['access_km_per_endpoint']*2
            hours=sum(float(r.travel_time_h) for r in legs)+CONFIG['access_km_per_endpoint']*2/25
            inbound_hours=float(legs[0].travel_time_h)+CONFIG['access_km_per_endpoint']/25
            basis='Saved OSM reference-to-facility distances; reverse warehouse leg assumes symmetric road access'
        from . import roads
        inbound=roads.saved(a['node'],warehouse.get('warehouse_id'))
        outbound=roads.saved(warehouse.get('warehouse_id'),b['node'])
        route_geometry=None
        if inbound and outbound:
            def leg_cost(leg):
                return (leg['road_km'] * truck['rs_km'] + leg['road_hours'] * congestion_pct * delay_rs_hour / 100,
                        leg['road_hours'])
            first=min(inbound,key=leg_cost);second=min(outbound,key=leg_cost)
            access=CONFIG['access_km_per_endpoint']*2+CONFIG.get('warehouse_access_km',1)*2
            km=first['road_km']+second['road_km']+access;hours=first['road_hours']+second['road_hours']+access/25
            inbound_hours=first['road_hours']+access/50
            basis='Directed OSM market-reference → warehouse → market-reference paths + assumed local access'
            first_line=json.loads(first['geometry'])
            second_line=json.loads(second['geometry'])
            # A snapped warehouse vertex joins both directed paths.
            if first_line and second_line and first_line[-1] == second_line[0]:
                route_geometry=first_line+second_line[1:]
        routes = [{'objective': 'via_storage', 'km': km, 'hours': hours, 'storage_arrival_hours': inbound_hours, 'basis': basis, 'origin': a['node'], 'destination': b['node']}]
        if route_geometry:
            routes[0].update(geometry=route_geometry, stop_index=len(first_line)-1)
    if planned:
        from . import roads
        for r in routes:
            if r['objective'] not in ('approximate', 'via_storage') or r.get('geometry'):
                continue
            endpoints = [(a['lat'], a['lng']), (b['lat'], b['lng'])]
            if days:
                endpoints.insert(1, (w['lat'], w['lng']))
            path = roads.cached_geometry(tuple(endpoints), 'shortest')
            if path and path['geometry']:
                access = CONFIG['access_km_per_endpoint'] * 2 + (CONFIG['warehouse_access_km'] * 2 if days else 0)
                r.update(geometry=path['geometry'], stop_index=path['stop_index'], km=path['road_km'] + access,
                         hours=path['road_hours'] + access / 25, basis='Local directed OSM road path + assumed endpoint access')
                if days:
                    r['storage_arrival_hours'] = path['inbound_hours'] + access / 50
    for r in routes:
        base_hours = r['hours']
        traffic_hours = base_hours * congestion_pct / 100
        handling_hours = loading_minutes / 60
        freight = round(r['km'] * truck['rs_km'] * (2 * trips - 1 if planned else trips), 2)
        toll = round(toll_rs_trip * trips, 2) if toll_rs_trip is not None else None
        delay_cost = round(traffic_hours * delay_rs_hour * trips, 2)
        r.update(base_hours=base_hours, hours=base_hours + traffic_hours + handling_hours,
                 traffic_hours=traffic_hours, loading_hours=handling_hours, base_freight=freight,
                 toll_cost=toll, delay_cost=delay_cost, transport_cost=round(freight + (toll or 0) + delay_cost, 2))
    route = routes[min(route_index-1, len(routes)-1)] if route_index else min(routes, key=lambda r: (r['transport_cost'],r['hours']))
    procurement = buy['predicted_price']*quantity
    storage = quantity*days*warehouse['rs_q_day'] if days else 0
    storage_handling=quantity*CONFIG.get('warehouse_handling_rs_q',0) if days else 0
    handling_cost = quantity*handling+storage_handling
    daily_loss=CONFIG['storage'][warehouse.get('storage_class') or storage_class(buy['crop'])].get('daily_loss_pct',0) if days else 0
    storage_loss=100*(1-(1-daily_loss/100)**days)
    total_loss=100*(1-(1-loss/100)*(1-storage_loss/100))
    sale_price = sell['predicted_price'] * (1+future_change/100 if days else 1)
    revenue = sale_price*quantity*(1-total_loss/100)
    cost = procurement+route['transport_cost']+storage+handling_cost
    scores = OUT / 'development/by_crop.csv'
    error = _planning_errors(str(scores), scores.stat().st_mtime_ns).get(buy['crop']) if scores.exists() else None
    if error is None:
        from .learning import score
        error=score(buy['crop']) or daily.error_information(buy['crop'])
    screen = 2*error['mae']*quantity if error else None
    result={'id': buy['series_id']+':'+sell['series_id'], 'crop': buy['crop'], 'buy': buy, 'sell': sell,
            'quantity_q': quantity, 'trips': trips, 'vehicle': vehicle, 'payload_q':truck['capacity_q'],'route': route, 'routes': routes,
            'storage_days': days, 'warehouse': warehouse if days else None,
            'procurement': round(procurement,2), 'transport': route['transport_cost'], 'handling': round(handling_cost,2),
            'storage': round(storage,2), 'total_cost': round(cost,2), 'sale_revenue': round(revenue,2),
            'margin': round(revenue-cost,2), 'uncertainty_screen': screen,
            'risk_adjusted_margin': round(revenue-cost-(screen or 0),2),
            'sale_price': round(sale_price,2), 'loss_pct': total_loss,'handling_loss_pct':loss,'storage_loss_pct':storage_loss,'storage_handling':storage_handling,
            'sale_basis': f'Future price scenario: {future_change:+g}% vs today; not a future forecast' if days else 'Current-day forecast',
            'explanation': 'Ranked after freight, handling, storage and handling losses. Historical error screens small price differences; similar options favour shorter trips.'}
    from .explanations import assess
    from .states import mode as classify,state_id
    result.update(trading_mode=classify(buy['state'],sell['state']),buy_state_id=state_id(buy['state']),sell_state_id=state_id(sell['state']))
    return assess(result,CONFIG['decision'])


@lru_cache(maxsize=2)
def _planning_errors(path, stamp):
    frame = pd.read_csv(path)
    return {row['crop']: row for row in frame[frame.model == 'persistence'].to_dict('records')}


def config_signature():
    geo=OUT/'phase2/district_references.json'
    from .explanations import ENGINE_VERSION,QUALITY
    routefile=OUT/'phase3/roads_v1/routes.parquet'
    market=OUT/'phase3/market_locations.json'
    local=OUT/'phase5/locality_references.json'
    return hashlib.sha256(json.dumps([ENGINE_VERSION,CONFIG,geo.stat().st_mtime_ns if geo.exists() else None,QUALITY.stat().st_mtime_ns if QUALITY.exists() else None,routefile.stat().st_mtime_ns if routefile.exists() else None,market.stat().st_mtime_ns if market.exists() else None,local.stat().st_mtime_ns if local.exists() else None],sort_keys=True).encode()).hexdigest()


def default_strategies():
    saved=OUT/'phase2/strategies.json'
    if saved.exists():
        held=json.loads(saved.read_text(encoding='utf-8'))
        from Code.daily.dataset import sha
        if held['batch_signature']==sha(DAILY/'batch.json') and held.get('config_signature')==config_signature() and held['date']==str(now_ist().date()):
            return held['rows'],held['candidate_count']
    return strategies()


def strategies(crop=None, state=None, quantity=100, vehicle='Medium truck', buy_id=None, sell_id=None,mode='both',details=False,selected_id=None,handling=None,loss=None,rs_km=None,capacity_q=None, integrated=False, warehouse_id=None, purchase_date=None, **transport):
    from .states import state_id,mode as classify,NAMES
    from .explanations import explain,rank
    _,_,_,pointer=daily.snapshot()
    raw_prices=current_prices()
    prices = [{**r, 'predicted_price': r['predicted_modal_price'], 'coordinate': market_coordinate(r)} for r in raw_prices]
    prices = [r for r in prices if r['coordinate'] and state_id(r['state'])]
    # Pair on exact forecast identities before any crop/state display filters.
    compatible={}
    for p in prices:compatible.setdefault(tuple(p[k] for k in ('crop','variety','grade','source')),[]).append(p)
    pairs=[(a,b,classify(a['state'],b['state'])) for group in compatible.values() for a in group for b in group if a['series_id']!=b['series_id']]
    supported={p['crop'] for group in compatible.values() if len(group)>1 for p in group}
    notices=[]
    states={state_id(p['state']) for group in compatible.values() if len(group)>1 for p in group if not crop or p['crop']==crop}
    requested_state=state_id(state) if state else None
    available={p['series_id'] for p in prices if not crop or p['crop']==crop}
    if (buy_id and buy_id not in available) or (sell_id and sell_id not in available):
        notices.append('The selected market series is unavailable for this comparison. Clear the selection to explore other trades.')
    scenarios=[]
    # Integrated filter options come from feasible direct plans before either
    # display filters or the storage search and result limits are applied.
    discover_regions = integrated and details and mode != 'both'
    def matches(row):
        return (not crop or row['crop'] == crop) and (
            not state or row['buy_state_id'] == requested_state)
    # Bounded current batch: enumerate every compatible mapped pair, not just price extremes.
    for buy in prices:
        if (buy_id and buy['series_id']!=buy_id) or (not discover_regions and (
            (crop and buy['crop']!=crop) or (state and state_id(buy['state'])!=requested_state))):
            continue
        for sell in compatible[tuple(buy[k] for k in ('crop','variety','grade','source'))]:
            if buy['series_id']==sell['series_id'] or (sell_id and sell['series_id']!=sell_id):
                continue
            if any(buy[k]!=sell[k] for k in ('crop','variety','grade','source')):
                continue
            scenario=calculate(buy,sell,quantity,vehicle,CONFIG['handling_rs_q'] if handling is None else handling,
                               CONFIG.get('crop_handling_loss_pct',{}).get(buy['crop'],CONFIG['handling_loss_pct']) if loss is None else loss,rs_km=rs_km,capacity_q=capacity_q,planned=integrated,**transport)
            scenario.update(trading_mode=classify(buy['state'],sell['state']),buy_state_id=state_id(buy['state']),sell_state_id=state_id(sell['state']))
            scenarios.append(scenario)
    feasible = []
    feasible_counts = {}
    if integrated and scenarios:
        from .planning import complete, candidates
        from .market_inventory import market_key
        now = now_ist().replace(second=0, microsecond=0)
        day = now.date()
        purchase_wait = (purchase_date - day).days if purchase_date is not None else None
        facilities = warehouses()
        direct_by_id = {row['id']: row for row in scenarios if market_key(row['buy']) != market_key(row['sell'])}
        feasible = [plan for row in direct_by_id.values() for route in row['routes']
                  if (plan := complete({**row, 'route': route, 'transport': route['transport_cost']}, day, now, purchase_wait or 0)) is not None]
        direct = [row for row in feasible if matches(row)]
        scenarios = []
        for category in ('intrastate', 'interstate'):
            ranked, _ = rank([r for r in direct if r['trading_mode'] == category], CONFIG['decision'])
            unique = {}
            for row in ranked:
                unique.setdefault(row['id'], row)
            feasible_counts[category] = len(unique)
            for index, row in enumerate(unique.values()):
                if index >= CONFIG['planning']['storage_pairs_per_mode']:
                    continue
                buy, sell = row['buy'], row['sell']
                pool = []
                if facilities:
                    compatible_facilities = [w for w in facilities if row['crop'] in w['supported_crops']
                                             and quantity <= w['free_t'] * 10
                                             and (not warehouse_id or warehouse_id == w['warehouse_id'])]
                    pool = sorted(compatible_facilities, key=lambda w: (
                        sum(distance(p['coordinate'], {'lat': w['latitude'], 'lng': w['longitude']}) for p in (buy, sell)),
                        w['warehouse_id']))[:CONFIG['planning']['warehouse_limit']]
                def storage(days, warehouse):
                    return calculate(buy, sell, quantity, vehicle, row['handling'] / quantity, row['handling_loss_pct'],
                                     days, warehouse, rs_km=rs_km, capacity_q=capacity_q, planned=True, **transport)
                plans, timing, unavailable = candidates(direct_by_id[row['id']], day, storage, pool, now, purchase_wait)
                if plans:
                    winner = plans[0]
                    # Keep selected geometry in its route. Alternatives reuse the same endpoint metadata.
                    compact = lambda plan: {**plan, 'routes': [{k: v for k, v in r.items() if k != 'geometry'} for r in plan['routes']]}
                    scenarios.append({**compact(winner), 'timing_options': [compact(plan) for plan in timing],
                                      'timing_unavailable': unavailable,
                                      'route_plans': [compact(plan) for plan in plans if not plan['storage_days']]})
    groups={};shortlist=[]
    for category in ('intrastate','interstate'):
        ranked,tolerance=rank([r for r in scenarios if r['trading_mode']==category],CONFIG['decision'])
        chosen=ranked[:12]
        selected=next((r for r in ranked if r['id']==selected_id),None)
        if selected and selected not in chosen:chosen.append(selected)
        for i,scenario in enumerate(chosen):
            scenario['decision']=explain(scenario,ranked[:24],tolerance)
            from .market_context import scenario_contribution
            scenario_contribution(scenario)
            scenario['decision'].update(scope='category_recommendation' if i==0 else 'selected_alternative',category=category)
            if len(ranked)>1 and i==0:
                from .explanations import comparison
                rival=comparison(scenario,ranked[1])
                scenario['decision']['next_alternative']=rival['insight']
                scenario['decision']['cards'][2]={'title':'Next alternative','value':ranked[1]['crop']+' · '+ranked[1]['sell']['market'],'text':rival['insight']}
        groups[category]={'rows':chosen,'candidate_count':len(ranked),
                          'feasible_candidate_count':feasible_counts.get(category,len(ranked)),
                          'evaluated_candidate_count':len(ranked),'best':chosen[0] if chosen else None,
                          'empty_reason':None if ranked else f'No compatible {category} market pairs match these filters.'}
        if mode in ('both',category):shortlist+=chosen
    leaders=[g['best'] for g in groups.values() if g['best']]
    leaders,_=rank(leaders,CONFIG['decision'])
    default_mode=leaders[0]['trading_mode'] if leaders else 'intrastate'
    active_mode=default_mode if mode in ('auto','both') else mode
    if mode=='auto':shortlist=list(groups[active_mode]['rows'])
    if mode!='both':
        supported={a['crop'] for a,b,category in pairs if category==active_mode and (not requested_state or state_id(a['state'])==requested_state)}
        states={state_id(a['state']) for a,b,category in pairs if category==active_mode and (not crop or a['crop']==crop)}
    if discover_regions:
        in_mode = [row for row in feasible if row['trading_mode'] == active_mode]
        states = {row['buy_state_id'] for row in in_mode if not crop or row['crop'] == crop}
        supported = {row['crop'] for row in in_mode}
    shortlist,_=rank(shortlist,CONFIG['decision'])
    if details:
        from .explanations import comparison
        competitors=groups[active_mode]['rows'][1:4]
        best=groups[active_mode]['best']
        selected=next((r for r in groups[active_mode]['rows'] if r['id']==selected_id),best)
        nearest=next((r for r in groups[active_mode]['rows'] if selected and r['id']!=selected['id']),None)
        empty=None
        if not best:
            empty=f'No compatible {active_mode} pairs match'+(f' {crop}' if crop else ' these filters')+'. Widen the purchase region, choose an eligible crop, or inspect current market forecasts.'
            if crop:
                from .availability import audit
                record=next((r for r in audit() if r['crop']==crop),None)
                if record and not record['eligible_pairs'][active_mode]:empty=record['reasons'][active_mode]+' Widen the region or choose another crop; the selected crop has been preserved.'
            if state and requested_state not in states:
                empty = 'No eligible purchase market in this region for the selected crop and trading mode.'
        if integrated:
            for group in groups.values():
                for row in group['rows']:
                    if row is not group['best'] and row['id'] != selected_id:
                        row.pop('timing_options', None)
                        row.pop('route_plans', None)
                        if row.get('route', {}).get('geometry'):
                            row['route'] = {k: v for k, v in row['route'].items() if k != 'geometry'}
        return {'rows':shortlist,'candidate_count':sum(g['candidate_count'] for k,g in groups.items() if mode=='both' or k==active_mode),
                'active_mode':active_mode,'default_mode':default_mode,'competitors':competitors,'selected_comparison':comparison(selected,nearest) if selected and nearest else None,
                'empty_explanation':empty,'fallback_crops':sorted({a['crop'] for a,b,category in pairs if category==active_mode}),
                'planning_horizon_days':CONFIG['planning']['horizon_days'],
                'groups':groups,'filters':{'crops':sorted(supported),'states':[{'id':k,'name':NAMES[k]} for k in sorted(states,key=lambda k:NAMES[k])]},
                'effective_filters':{'crop':crop or '', 'state':requested_state or state or '', 'buy_id':buy_id or '', 'sell_id':sell_id or '', 'mode':active_mode},
                'notices':notices,'date':str(now_ist().date()),'dataset_version':pointer['dataset_version'],'batch_id':pointer['sha256'],
                'forecast_count':len(raw_prices),'batch_current':pointer.get('target_date')==str(now_ist().date()),
                'forecast_ready_crops':sorted({p['crop'] for p in raw_prices}),'strategy_ready_crops':sorted(supported)}
    return shortlist,len(scenarios)
