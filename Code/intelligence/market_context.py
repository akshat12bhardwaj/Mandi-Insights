"""Transparent market intelligence over existing observed/forecast/logistics data."""
from statistics import median
from fastapi import HTTPException
from Code.api import daily
from . import service as s,roads,environment,market_inventory as inventory

def resolve(crop,series_id):
    s.valid_crop(crop)
    row = inventory.index()[1].get(series_id)
    if row is None or row['crop'] != crop:
        raise HTTPException(404,'Market series is unavailable for this crop')
    coordinate = s.market_coordinate(row)
    if coordinate is None:
        from .warehouse_context import _mapped
        coordinate = dict(_mapped(daily._signature(), s.config_signature())).get(inventory.market_key(row))
    return {**inventory.public(row, inventory.forecast_is_current(daily.snapshot()[3])), 'coordinate': coordinate}


def facility_leg(coordinate, warehouse, aerial, links):
    access = s.CONFIG['access_km_per_endpoint'] + s.CONFIG['warehouse_access_km']
    options = roads.saved(coordinate['node'], warehouse['warehouse_id'])
    if options:
        route = min(options, key=lambda r: r['road_km'])
        return (route['road_km'] + access, route['road_hours'] + access / 25, 'directed_road',
                'Directed OSM reference-to-warehouse road path plus assumed local access')
    legacy = links[(links.node_id == coordinate['node']) & (links.warehouse_id == warehouse['warehouse_id'])] if links is not None else None
    if legacy is not None and len(legacy):
        route = legacy.iloc[0]
        access = s.CONFIG['access_km_per_endpoint']
        return (float(route.road_distance_km) + access, float(route.travel_time_h) + access / 25, 'saved_road',
                'Saved OSM reference-to-warehouse distance plus assumed market access')
    km = aerial * s.CONFIG['road_detour_factor'] + access
    return km, km / 35, 'approximate', 'Approximate distance from mapped references'

def warehouse_options(market,quantity=100,prefer_compatible=True):
    coordinate=market.get('coordinate')
    if not coordinate:return {'rows':[],'compatible_count':0,'radius_km':s.CONFIG['market_context']['nearby_radius_km'],'reason':'No accepted market reference; distance was not guessed.'}
    radius=s.CONFIG['market_context']['nearby_radius_km'];rows=[];links=s.lg.node_warehouse()
    for w in s.warehouses():
        aerial=s.distance(coordinate,{'lat':w['latitude'],'lng':w['longitude']})
        if aerial>radius:continue
        km,hours,kind,basis=facility_leg(coordinate,w,aerial,links)
        compatible=market['crop'] in w['supported_crops'];capacity=w['free_t']>=quantity/10
        note=('Compatible storage with enough simulated space for this load.' if compatible and capacity else 'Crop compatible, but simulated free space is below this load.' if compatible else 'This project storage class does not support the selected crop.')
        rows.append({**w,'distance_km':round(km,1),'hours':round(hours,2),'distance_kind':kind,'distance_basis':basis,
                     'compatible':compatible,'enough_capacity':capacity,'seven_day_charge':round(quantity*7*w['rs_q_day'],2) if compatible and w['max_days']>=7 else None,
                     'usefulness':note,'handling_and_loss_extra':True})
    compatible_count=sum(r['compatible'] and r['enough_capacity'] for r in rows)
    rows.sort(key=lambda r:(prefer_compatible and not(r['compatible'] and r['enough_capacity']),r['distance_km'],r['warehouse_id']))
    return {'rows':rows[:5],'compatible_count':compatible_count,'known_facilities_in_radius':len(rows),'radius_km':radius,
            'radius_basis':'Straight-line screening radius; displayed journey distances may be longer. Project inventory is incomplete.',
            'quantity_q':quantity,'reason':None if rows else 'No known project facilities lie inside this screening radius.'}

def reduced(row):
    return {'id':row['id'],'buy_id':row['buy']['series_id'],'sell_id':row['sell']['series_id'],'buy_market':row['buy']['market'],'sell_market':row['sell']['market'],
            'net_margin':row['margin'],'adjusted_value':row['risk_adjusted_margin'],'freight':row['transport'],'quantity_q':row['quantity_q'],
            'distance_km':row['route']['km'],'hours':row['route']['hours'],'route_basis':row['route']['basis'],'objective':row['route']['objective']}


def directional_trades(market, current, peers, quantity):
    from .states import mode
    buying, selling = [], []
    if market.get('coordinate'):
        own = {**current, 'predicted_price': current['predicted_modal_price'], 'coordinate': market['coordinate']}
        for peer in peers:
            if mode(market['state'], peer['state']) is None or inventory.market_key(market) == inventory.market_key(peer):
                continue
            coordinate = s.market_coordinate(peer)
            if not coordinate:
                continue
            other = {**peer, 'predicted_price': peer['predicted_modal_price'], 'coordinate': coordinate}
            for buy, sell, rows in ((own, other, buying), (other, own, selling)):
                rows.append(s.calculate(buy, sell, quantity, 'Medium truck', s.CONFIG['handling_rs_q'],
                                        s.CONFIG['crop_handling_loss_pct'].get(market['crop'], s.CONFIG['handling_loss_pct'])))
    return buying, selling


def opportunities(series_id, side, pointer):
    from .explanations import comparison, rank
    locations, by_id = inventory.index()
    if series_id not in by_id:
        raise HTTPException(404, 'Market series is unavailable')
    if not inventory.forecast_is_current(pointer):
        return []
    key = inventory.market_key(by_id[series_id])
    local_ids = {row['series_id'] for row in locations[key]}
    prices = s.current_prices()
    by_crop = {}
    for row in prices:
        if row['series_id'] not in local_ids:
            continue
        peers = [peer for peer in prices if peer['series_id'] != row['series_id']
                 and all(peer[k] == row[k] for k in ('crop', 'variety', 'grade', 'source'))]
        buying, selling = directional_trades({**row, 'coordinate': s.market_coordinate(row)}, row, peers, 100)
        by_crop.setdefault(row['crop'], []).extend(buying if side == 'buy' else selling)
    leaders, explanations = [], {}
    for candidates in by_crop.values():
        ranked, _ = rank([row for row in candidates if row['risk_adjusted_margin'] > 0], s.CONFIG['decision'])
        if not ranked:
            continue
        leader = ranked[0]
        leaders.append(leader)
        rival = next((row for row in ranked[1:] if all(row['buy'][k] == leader['buy'][k]
                     for k in ('variety', 'grade', 'source'))), None)
        explanations[leader['id']] = (comparison(leader, rival)['insight'], reduced(rival)) if rival else (None, None)
    leaders, _ = rank(leaders, s.CONFIG['decision'])
    return [{**reduced(row), 'crop': row['crop'], 'variety': row['buy']['variety'],
             'grade': row['buy']['grade'], 'source': row['buy']['source'],
             'handling': row['handling'], 'comparison': explanations[row['id']][0],
             'alternative': explanations[row['id']][1]} for row in leaders]


def price_decision(market,prices,quantity):
    current=next((r for r in prices if r['series_id']==market['series_id']),None)
    peers=[r for r in prices if r['series_id']!=market['series_id'] and all(r[k]==market[k] for k in ('crop','variety','grade','source'))]
    basis='Exact crop, variety, grade and source; current eligible forecasts only.'
    if not current:return {'role':'observe','headline':'Historical observation only','explanation':'No eligible current forecast exists for this series. Its old reported price is not used to recommend a present-day trade.',
        'peer_count':0,'peer_basis':basis,'best_buy':None,'best_sell':None,'pair_count':0,'connections':[]}
    from .explanations import rank
    buying, selling = directional_trades(market, current, peers, quantity)
    buying,_=rank(buying,s.CONFIG['decision']);selling,_=rank(selling,s.CONFIG['decision'])
    best_buy=buying[0] if buying else None;best_sell=selling[0] if selling else None
    candidates=[(r,role) for r,role in ((best_buy,'buy'),(best_sell,'sell')) if r]
    choice,role=max(candidates,key=lambda r:r[0]['risk_adjusted_margin']) if candidates else (None,'observe')
    if choice and choice['risk_adjusted_margin']>0:
        text=(f"Procurement candidate: delivery to {choice['sell']['market']} leaves ₹{choice['margin']:,.0f} modeled margin after ₹{choice['transport']:,.0f} freight." if role=='buy' else
              f"Selling candidate: procurement in {choice['buy']['market']} leaves ₹{choice['margin']:,.0f} modeled margin after ₹{choice['transport']:,.0f} freight.")
        title='Stronger for procurement' if role=='buy' else 'Stronger as a selling point'
    else:
        role='observe';title='Watch prices before committing'
        text='Compatible spreads do not clear the configured uncertainty and logistics screens.' if choice else 'No compatible mapped trading pair is available; a forecast alone does not establish a feasible trade.'
    peer_median=median([r['predicted_modal_price'] for r in peers]) if peers else None
    linked=sorted([r for r in buying],key=lambda r:(r['route']['objective']=='approximate',r['route']['km']))[:3]
    return {'role':role,'headline':title,'explanation':text,'peer_count':len(peers),'peer_basis':basis,'peer_median':peer_median,
            'difference_from_peer_median':round(current['predicted_modal_price']-peer_median,2) if peer_median is not None else None,
            'best_buy':reduced(best_buy) if best_buy else None,'best_sell':reduced(best_sell) if best_sell else None,
            'pair_count':len(buying)+len(selling),'connections':[reduced(r) for r in linked],
            'ranking_policy':'Existing margin, forecast-error, report-age, price-movement and route-evidence policy. Net margin is separate from adjusted value.'}

def detail(crop,series_id,quantity=100):
    market=resolve(crop,series_id);_,_,_,pointer=daily.snapshot();prices=s.current_prices()
    history_note=None
    try:history=daily.history(series_id,60)
    except HTTPException as exc:
        if exc.status_code not in (404,503):raise
        history={'points':[]};history_note='Observed history unavailable or not integrated for this series; no trend was synthesized.'
    points=history['points'];first,last=(points[0],points[-1]) if points else (None,None)
    trend=round(100*(last['price']/first['price']-1),1) if first and first['price'] else None
    activity = inventory.inventory(series_id, pointer, limit=0)
    warehouses=warehouse_options(market,quantity);decision=price_decision(market,prices,quantity)
    if warehouses['compatible_count']:decision['storage_note']=f"{warehouses['compatible_count']} known compatible facilities within the {warehouses['radius_km']} km screening radius have enough simulated free space. Storage expense and price-horizon uncertainty still need comparison."
    else:decision['storage_note']='No compatible facility with sufficient simulated capacity was found inside the project screening radius; this does not establish that no real facility exists.'
    env=environment.context(market.get('coordinate'))
    coordinate=market.get('coordinate');node=next((r for r in s.nodes() if coordinate and r['node_id']==coordinate['node']),None)
    access={'mapped':bool(coordinate),'precision':coordinate['precision'] if coordinate else 'Unmapped',
            'snap_gap_km':node.get('access_gap_km') if node else None,'network_status':node.get('network_status') if node else None,
            'connections':decision['connections'],'note':'Saved road evidence connects reference points. Local approach distances and travel time remain estimates; no live closures or traffic feed.' if coordinate else 'No accepted location reference; no approach road was invented.'}
    return {'market':market,'location':coordinate,'price':{'kind':'forecast' if market.get('predicted_price') else 'observed','current_estimate':market.get('predicted_price'),
                'latest_observed':{'date':market['observation_date'],'price':market['last_observed_price']},
                'forecast_input_date':next((r['last_observation_date'] for r in prices if r['series_id']==series_id),None),
                'history':points,'history_note':history_note,'trend_pct':trend,'trend_reports':len(points),'unit':'INR/quintal'},
            'activity':activity,
            'warehouses':warehouses,'access':access,'decision':decision,'environment':env,'quantity_q':quantity,
            'dataset_version':pointer['dataset_version'],'batch_id':pointer['sha256']}

def scenario_contribution(row):
    """Annotation only. Never fetch weather or train inside trading requests."""
    notes=[];coverage={}
    for side in ('buy','sell'):
        market=row[side];env=environment.context(market.get('coordinate'))
        coverage[side]={'weather_available':env.get('available',False),'weather_stale':env.get('weather_stale',False),
                        'terrain_available':env.get('terrain',{}).get('available',False)}
        notes.extend(market['market']+': '+note for note in env.get('cautions',[]))
    row['market_context']={'cautions':notes[:3],'coverage':coverage,'policy':'Practical context only. No price adjustment or unsupported weather/terrain score; storage feasibility is enforced by the storage calculator.'}
    if row.get('decision'):row['decision']['context_notes']=notes[:2]
    return row
