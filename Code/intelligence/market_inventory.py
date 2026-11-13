"""Market identity and inventory over the audited, published daily release."""
from collections import defaultdict
from functools import lru_cache
import json

import pandas as pd
from fastapi import HTTPException

from Code.api import daily
from Code.daily.policy import text, now_ist
from . import service as s
from .states import NAMES, state_id


def region_key(value):
    return state_id(value) or text(value).casefold()


def market_key(row):
    return (region_key(row['state']),
            text(row['district']).casefold(), text(row['market']).casefold())


@lru_cache(maxsize=2)
def _index(signature):
    _, _, batch, _ = daily._snapshot(signature)
    locations = defaultdict(list)
    by_id = {}
    with batch.connect() as db:
        for (raw,) in db.execute('SELECT payload FROM predictions'):
            row = json.loads(raw)
            observed_today = row.get('observed_today')
            observed = observed_today if observed_today is not None else row['last_observed_price']
            if observed is None:
                continue
            series = {key: row[key] for key in
                      ('series_id', 'crop', 'variety', 'grade', 'source', 'state', 'district', 'market')}
            series.update(last_observed_price=observed,
                          observation_date=row['target_date'] if observed_today is not None else row['last_observation_date'],
                          batch_price=row['predicted_modal_price'])
            locations[market_key(series)].append(series)
            by_id[series['series_id']] = series
    return locations, by_id


def index():
    return _index(daily._signature())


def forecast_is_current(pointer):
    now = now_ist()
    return pointer['target_date'] == str(now.date()) and pd.Timestamp(pointer['issue']) <= pd.Timestamp(now)


def public(row, current):
    result = {key: value for key, value in row.items() if key != 'batch_price'}
    estimate = row['batch_price'] if current else None
    return {**result, 'predicted_price': estimate, 'forecast_ready': estimate is not None,
            'status': 'Estimated today' if estimate is not None else
                      'Historical observations' if row['source'] == 'agmarknet_archive' else 'Reported observations'}


def inventory(series_id, pointer, search='', sort='crop', offset=0, limit=10):
    from .explanations import quality_for

    locations, by_id = index()
    anchor = by_id.get(series_id)
    if anchor is None:
        raise HTTPException(404, 'Market series is unavailable')
    current = forecast_is_current(pointer)
    records = locations[market_key(anchor)]
    terms = text(search).casefold().split()
    rows = [public(row, current) for row in records
            if all(term in ' '.join(row[k] for k in ('crop', 'variety', 'grade', 'source')).casefold()
                   for term in terms)]
    rows.sort(key=lambda r: (r['crop'].casefold(), r['variety'].casefold(), r['grade'], r['source'], r['series_id']))
    if sort == 'latest':
        rows.sort(key=lambda r: r['observation_date'] or '', reverse=True)
    if sort == 'forecast':
        rows.sort(key=lambda r: not r['forecast_ready'])
    page = rows[offset:offset + limit]
    for row in page:
        quality = quality_for(row['series_id']) if row['forecast_ready'] else None
        row['recent_movement_rs'] = quality.get('recent_step_variation_rs') if quality else None
    return {'rows': page, 'total': len(rows), 'total_series': len(records),
            'crop_count': len({r['crop'] for r in records}),
            'forecast_series': sum(current and r['batch_price'] is not None for r in records)}


def discovery(pointer, crop, state, district, search, recent, min_price, max_price, offset, limit):
    locations, _ = index()
    current = forecast_is_current(pointer)
    candidates = [row for records in locations.values() for row in records if not crop or row['crop'] == crop]
    term = text(search).casefold()
    region = region_key(state) if state else ''
    states = sorted({NAMES.get(region_key(row['state']), row['state']) for row in candidates})
    districts = sorted({row['district'] for row in candidates if not region or region_key(row['state']) == region})
    rows = {}
    for row in candidates:
        if (region and region_key(row['state']) != region or district and row['district'] != district
                or (term and term not in text(row['market']).casefold())):
            continue
        estimate = row['batch_price'] if current else None
        price = estimate if estimate is not None else row['last_observed_price']
        if (recent and estimate is None) or not min_price <= price <= max_price:
            continue
        key = row['series_id'] if crop else market_key(row)
        existing = rows.get(key)
        priority = (estimate is not None, row['observation_date'] or '', row['series_id'])
        if existing is None or priority > existing[0]:
            rows[key] = priority, row
    ordered = [public(row, current) for _, row in rows.values()]
    if crop:
        ordered.sort(key=lambda r: (not r['forecast_ready'], r['predicted_price'] or r['last_observed_price'], r['series_id']))
    else:
        ordered.sort(key=lambda r: (not r['forecast_ready'], r['market'].casefold(), market_key(r), r['series_id']))
    page = ordered[offset:offset + limit]
    for row in page:
        row['coordinate'] = s.market_coordinate(row)
    mapped = [r for r in page if r['coordinate']]
    return {'rows': page, 'total': len(ordered), 'states': states, 'districts': districts,
            'mapped_count': len(mapped), 'unmapped_count': len(page) - len(mapped),
            'map_points': [{'id': i, 'lat': r['coordinate']['lat'], 'lng': r['coordinate']['lng'],
                            'label': ' · '.join(r[k] for k in ('market', 'state', 'district', 'crop')),
                            'series_id': r['series_id'], 'tone': 'ok' if r['forecast_ready'] else 'muted'}
                           for i, r in enumerate(mapped)]}


def map_inventory(pointer, crop, state, search, basis):
    from .warehouse_context import _mapped

    locations, _ = index()
    coordinates = dict(_mapped(daily._signature(), s.config_signature()))
    current = forecast_is_current(pointer)
    term = text(search).casefold()
    states = {}
    region = region_key(state) if state else ''
    points, unmapped, prices = [], [], []
    missing = 0
    for key, records in locations.items():
        eligible = [r for r in records if (not crop or r['crop'] == crop)
                    and (basis != 'forecast' or current and r['batch_price'] is not None)]
        if not eligible:
            continue
        states.setdefault(key[0], NAMES.get(key[0], eligible[0]['state']))
        if term and term not in ' '.join(key[1:]) and not any(
                term in name.casefold() for name in [states[key[0]], *(r['state'] for r in eligible)]):
            continue
        if region and key[0] != region:
            continue
        row = max(eligible, key=lambda r: (r['observation_date'] or '', r['series_id']))
        price = (row['batch_price'] if basis == 'forecast' else row['last_observed_price']) if crop else None
        if price is not None:
            prices.append(price)
        item = {'series_id': row['series_id'], 'crop': row['crop'], 'price': price,
                'label': ', '.join((row['market'], row['district'], states[key[0]]))}
        coordinate = coordinates.get(key)
        if coordinate:
            points.append({**item, 'id': len(points), 'lat': coordinate['lat'], 'lng': coordinate['lng'],
                           'approximate': not coordinate['node'].startswith('M:')})
        else:
            missing += 1
            if region or len(unmapped) < 12:
                unmapped.append(item)
    options = [{'id': k, 'name': v} for k, v in sorted(states.items(), key=lambda pair: pair[1])]
    return {'points': points, 'unmapped': unmapped, 'unmapped_count': missing,
            'states': [option['name'] for option in options], 'state_options': options, 'selected_state_id': region,
            'bounds': [min(prices), max(prices)] if prices else None}
