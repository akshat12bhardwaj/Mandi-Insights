"""Bounded operational planning over published quotes and existing cost policies."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from Code.daily.policy import IST
from . import future, service as s
from .explanations import assess, rank


def schedule(day, route, trips, storage_days, wait=0, ready_at=None):
    policy = s.CONFIG['planning']
    procurement = datetime.combine(day + timedelta(days=wait), datetime.min.time(), IST).replace(hour=8)
    if ready_at is not None:
        procurement = max(procurement, ready_at)
    loading = policy['loading_minutes'] / 60
    driving = route.get('base_hours', route['hours']) + route.get('traffic_hours', 0)
    # Each outbound load uses the same truck. Between loads it returns empty.
    inbound = route.get('storage_arrival_hours')
    if storage_days and inbound is None:
        raise ValueError('Storage requires an inbound time estimate')
    travel = driving * (2 * trips - 1)
    loading_total = loading * trips
    handling_total = (policy['unloading_minutes'] / 60 + route.get('loading_hours', 0)) * trips
    storage_start = procurement + timedelta(hours=inbound * (2 * trips - 1) + loading_total + handling_total) if storage_days else None
    storage_end = storage_start + timedelta(days=storage_days) if storage_start else None
    arrival = procurement + timedelta(hours=travel + loading_total + handling_total, days=storage_days)
    return {'procurement_at': procurement.isoformat(), 'depart_at': (procurement + timedelta(hours=loading)).isoformat(),
            'storage_start_at': storage_start.isoformat() if storage_start else None,
            'storage_end_at': storage_end.isoformat() if storage_end else None,
            'arrival_at': arrival.isoformat(), 'sale_at': arrival.isoformat(),
            'elapsed_hours': round((arrival - procurement).total_seconds() / 3600, 2),
            'travel_hours': round(travel, 2), 'loading_hours': round(loading_total, 2)}


def quote(price, day, horizon):
    target = (day + timedelta(days=horizon)).isoformat()
    if horizon in future.HORIZONS and price.get('target_date') == day.isoformat():
        try:
            forecast = future.forecast(price, horizon)
        except ValueError:
            forecast = None
        if (forecast and forecast.get('kind') == 'future_forecast'
                and forecast.get('target_date') == target and forecast.get('horizon_days') == horizon
                and all(forecast.get(key) == price.get(key) for key in ('series_id', 'crop', 'dataset_version'))
                and forecast.get('base_price_issue') == price.get('forecast_issue_timestamp')
                and isinstance(forecast.get('price'), (int, float))
                and isfinite(forecast['price']) and forecast['price'] > 0
                and isinstance(forecast.get('historical_mae'), (int, float))
                and isfinite(forecast['historical_mae']) and forecast['historical_mae'] >= 0):
            return forecast
    return {'kind': 'persistence_assumption' if horizon else 'current_forecast',
            'target_date': target, 'horizon_days': horizon, 'price': price['predicted_price']}


def complete(row, day, ready_at=None, wait=0, scenario_price=None):
    timing = schedule(day, row['route'], row['trips'], row['storage_days'], wait, ready_at)
    horizon = (datetime.fromisoformat(timing['sale_at']).date() - day).days
    if horizon < 0 or horizon > s.CONFIG['planning']['horizon_days']:
        return None
    price = (quote(row['sell'], day, horizon) if scenario_price is None else
             {'kind': 'scenario', 'target_date': timing['sale_at'][:10], 'horizon_days': horizon, 'price': scenario_price})
    money = lambda value: float(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    saleable = Decimal(str(row['quantity_q'])) * (1 - Decimal(str(row['loss_pct'])) / 100)
    revenue = money(saleable * Decimal(str(price['price'])))
    expenses = money(sum(Decimal(str(row[key])) for key in ('procurement', 'transport', 'handling', 'storage')))
    screen = row['uncertainty_screen']
    if price['kind'] == 'future_forecast':
        screen = 2 * price['historical_mae'] * row['quantity_q']
    elif horizon:
        # Carry forward the existing error floor and increase the planning reserve with elapsed days.
        screen = max(screen or 0, .10 * revenue) * (1 + min(horizon, 30) / 30)
    if row.get('buy_quote'):
        buy_quote = row['buy_quote']
        purchase_reserve = buy_quote['historical_mae'] * row['quantity_q'] if 'historical_mae' in buy_quote else .10 * row['procurement']
        screen = (screen or 0) + purchase_reserve
    result = {**row, 'schedule': timing, 'sale_quote': price, 'sale_price': price['price'],
              'sale_basis': {'future_forecast': 'Evaluated forecast for the planned sale date',
                             'persistence_assumption': 'Current price carried forward to the planned sale date',
                             'current_forecast': 'Current-day estimate',
                             'scenario': 'Manual price scenario'}[price['kind']],
              'saleable_q': float(saleable), 'sale_revenue': revenue, 'total_cost': expenses,
              'margin': money(Decimal(str(revenue)) - Decimal(str(expenses))), 'uncertainty_screen': screen}
    if price['kind'] == 'future_forecast':
        result['future_forecast'] = price
    return assess(result, s.CONFIG['decision'])


def candidates(direct, day, calculate_storage, warehouses, ready_at=None, purchase_wait=None):
    def priced(row, wait):
        if wait:
            buying = quote(row['buy'], day, wait)
            row = {**row, 'buy': {**row['buy'], 'predicted_price': buying['price']},
                   'procurement': float((Decimal(str(buying['price'])) * Decimal(str(row['quantity_q']))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
                   'buy_quote': buying}
        return complete(row, day, ready_at, wait)

    options = [priced({**direct, 'route': route, 'transport': route['transport_cost']}, purchase_wait or 0) for route in direct['routes']]
    unavailable = []
    for days in future.HORIZONS:
        rows = [priced(calculate_storage(days, w), purchase_wait or 0) for w in warehouses if days <= w['max_days']]
        if any(rows):
            options.extend(rows)
        else:
            unavailable.append({'days': days, 'reason': 'No compatible storage plan fits capacity and the planning window.'})
    ranked, _ = rank([row for row in options if row is not None], s.CONFIG['decision'])
    timing = {}
    for row in ranked:
        timing.setdefault(row['storage_days'], row)
    return ranked, list(timing.values()), unavailable
