"""Warehouse comparisons using published prices and the shared scenario calculator."""
from collections import defaultdict
from functools import lru_cache
import math
from statistics import median

from fastapi import HTTPException

from . import future, market_inventory as inventory, service as s, storage_decisions
from .market_context import facility_leg, reduced
from .states import mode


def facility(warehouse_id):
    row = next((row for row in s.warehouses() if row['warehouse_id'] == warehouse_id), None)
    if row is None:
        raise HTTPException(404, 'Warehouse unavailable')
    return row


@lru_cache(maxsize=2)
def _mapped(signature, geography):
    locations, _ = inventory._index(signature)
    points = []
    for key, records in locations.items():
        coordinate = s.market_coordinate(records[0])
        if coordinate:
            points.append((key, coordinate))
    return points


def nearby(warehouse, pointer, quantity, crop=None):
    from Code.api import daily
    locations, _ = inventory.index()
    reference = {'lat': warehouse['latitude'], 'lng': warehouse['longitude']}
    radius = s.CONFIG['market_context']['nearby_radius_km']
    current = inventory.forecast_is_current(pointer)
    links = s.lg.node_warehouse()
    truck = s.CONFIG['vehicles']['Medium truck']
    candidates = []
    peer_quotes = defaultdict(dict)
    for key, coordinate in _mapped(daily._signature(), s.config_signature()):
        aerial = s.distance(coordinate, reference)
        if aerial > radius:
            continue
        records = locations[key]
        relevant = [row for row in records if not crop or row['crop'] == crop]
        if relevant:
            candidates.append((aerial, key, coordinate, relevant))
            for row in relevant:
                if current and row['batch_price'] is not None:
                    identity = tuple(row[k] for k in ('crop', 'variety', 'grade', 'source'))
                    quote = (row['observation_date'] or '', row['series_id'], row['batch_price'])
                    previous = peer_quotes[identity].get(key)
                    if previous is None or quote > previous:
                        peer_quotes[identity][key] = quote
    rows = []
    for aerial, key, coordinate, relevant in sorted(candidates)[:10]:
        anchor = max(relevant, key=lambda r: (current and r['batch_price'] is not None,
                                             r['observation_date'] or '', r['series_id']))
        km, _, kind, basis = facility_leg(coordinate, warehouse, aerial, links)
        identity = tuple(anchor[k] for k in ('crop', 'variety', 'grade', 'source'))
        peers = [quote[2] for other, quote in peer_quotes[identity].items() if other != key]
        rows.append({**inventory.public(anchor, current), 'coordinate': coordinate,
                     'reported_crops': sorted({row['crop'] for row in locations[key]}),
                     'distance_km': round(km, 1), 'distance_kind': kind, 'distance_basis': basis,
                     'freight': round(km * truck['rs_km'] * math.ceil(quantity / truck['capacity_q']), 2),
                     'comparable_markets': len(peers), 'peer_median_price': median(peers) if peers else None})
    return {'rows': rows, 'radius_km': radius, 'total': len(candidates)}


def opportunities(warehouse, request, crop=None, series_id=None):
    from .explanations import rank

    reference = {'lat': warehouse['latitude'], 'lng': warehouse['longitude']}
    radius = s.CONFIG['market_context']['nearby_radius_km']
    prices = defaultdict(list)
    for row in s.current_prices():
        if row['crop'] not in warehouse['supported_crops'] or (crop and row['crop'] != crop):
            continue
        coordinate = s.market_coordinate(row)
        if coordinate:
            key = tuple(row[k] for k in ('crop', 'variety', 'grade', 'source'))
            prices[key].append({**row, 'coordinate': coordinate, 'predicted_price': row['predicted_modal_price']})
    pairs = defaultdict(list)
    for group in prices.values():
        for buy in group:
            if (series_id and buy['series_id'] != series_id) or s.distance(reference, buy['coordinate']) > radius:
                continue
            for sell in group:
                if inventory.market_key(buy) == inventory.market_key(sell) or not mode(buy['state'], sell['state']):
                    continue
                loss = s.CONFIG['crop_handling_loss_pct'].get(buy['crop'], s.CONFIG['handling_loss_pct'])
                direct_request = request.model_copy(update={'days': 0, 'warehouse_id': None, 'loss': loss})
                try:
                    direct = storage_decisions.calculate(buy, sell, direct_request, annotate=False)
                except ValueError as exc:
                    if str(exc) != 'The journey exceeds the planning window':
                        raise
                    continue
                pairs[buy['crop']].append(direct)
    results = []
    for options in pairs.values():
        shortlist, _ = rank(options, s.CONFIG['decision'])
        for direct in shortlist[:3]:
            buy, sell = direct['buy'], direct['sell']
            for days in future.HORIZONS:
                load = {'crop': buy['crop'], 'quantity_q': request.quantity, 'days': days}
                if not s.allocation(warehouse, [load])['feasible']:
                    continue
                scenario = request.model_copy(update={'days': days, 'warehouse_id': warehouse['warehouse_id'],
                                                      'loss': direct['handling_loss_pct']})
                try:
                    stored = storage_decisions.calculate(buy, sell, scenario, annotate=False)
                except ValueError as exc:
                    if str(exc) != 'The journey exceeds the planning window':
                        raise
                    continue
                results.append({**reduced(stored), 'crop': buy['crop'], 'variety': buy['variety'],
                                'grade': buy['grade'], 'source': buy['source'], 'days': days,
                                'storage': stored['storage'], 'handling': stored['handling'],
                                'loss_pct': stored['loss_pct'], 'sale_price': stored['sale_price'],
                                'sale_revenue': stored['sale_revenue'], 'sale_kind': stored['sale_kind'],
                                'immediate_margin': direct['margin'],
                                'margin_difference': round(stored['margin'] - direct['margin'], 2),
                                'adjusted_difference': round(stored['risk_adjusted_margin'] - direct['risk_adjusted_margin'], 2),
                                'future_change': request.future_change})
    return sorted(results, key=lambda row: (-row['adjusted_difference'], -row['adjusted_value'], row['days'], row['id']))
