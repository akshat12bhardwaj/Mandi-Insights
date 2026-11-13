from datetime import date, datetime, timedelta

import pytest

from Code.daily.policy import IST
from Code.intelligence import planning as p, service as s
from Code.tests.test_dynamic_intelligence import market_prices  # pytest fixture


def test_sequential_trips_and_storage_dates():
    row = p.schedule(date(2026, 11, 13), {'hours': 10, 'storage_arrival_hours': 4}, 2, 7)
    assert row['travel_hours'] == 30
    assert row['storage_end_at'] == '2026-11-20T22:00:00+05:30'
    assert row['sale_at'] == '2026-11-21T16:00:00+05:30'
    late = p.schedule(date(2026, 11, 13), {'hours': 2}, 1, 0, ready_at=datetime(2026, 11, 13, 22, tzinfo=IST))
    assert late['arrival_at'].startswith('2026-11-14')


def test_quote_uses_exact_horizon_and_labels_missing_coverage(monkeypatch):
    day = date(2026, 11, 13)
    price = {'crop': 'Onion', 'series_id': 'onion', 'dataset_version': 'current',
             'predicted_price': 2000, 'target_date': day.isoformat()}
    forecast = {'kind': 'future_forecast', 'crop': 'Onion', 'series_id': 'onion', 'dataset_version': 'current',
                'price': 2600, 'target_date': '2026-11-20', 'horizon_days': 7, 'historical_mae': 120}
    def serve(price, horizon):
        if horizon != 7:
            raise ValueError('Insufficient coverage')
        return forecast
    monkeypatch.setattr(p.future, 'forecast', serve)
    assert p.quote(price, day, 7) == forecast
    assert p.quote(price, day, 2)['kind'] == 'persistence_assumption'
    assert p.quote(price, day, 14)['kind'] == 'persistence_assumption'
    for key, wrong in [('target_date', '2026-11-21'), ('series_id', 'other'), ('dataset_version', 'previous')]:
        with monkeypatch.context() as m:
            m.setattr(p.future, 'forecast', lambda *args: {**forecast, key: wrong})
            fallback = p.quote(price, day, 7)
            assert (fallback['kind'], fallback['target_date'], fallback['price']) == ('persistence_assumption', '2026-11-20', 2000)


def test_complete_plan_reconciles_expenses_and_rejects_beyond_horizon(monkeypatch):
    monkeypatch.setattr(p, 'assess', lambda row, config: row)
    row = {'route': {'hours': 18}, 'trips': 1, 'storage_days': 0, 'sell': {'predicted_price': 1500},
           'quantity_q': 100, 'loss_pct': 2, 'procurement': 100000, 'transport': 4000,
           'handling': 1800, 'storage': 0, 'uncertainty_screen': 5000}
    result = p.complete(row, date(2026, 11, 13))
    assert result['sale_quote']['target_date'] == '2026-11-14'
    assert result['saleable_q'] == 98 and result['sale_revenue'] == 147000
    assert result['total_cost'] == 105800 and result['margin'] == 41200
    assert p.complete({**row, 'trips': s.CONFIG['planning']['horizon_days'] * 2}, date(2026, 11, 13)) is None


def test_default_procurement_does_not_wait_for_a_cheaper_quote(monkeypatch):
    day = date(2026, 11, 13)
    monkeypatch.setattr(p, 'quote', lambda *args: {'kind': 'future_forecast', 'price': 50})
    monkeypatch.setattr(p, 'complete', lambda row, *args: row)
    monkeypatch.setattr(p, 'rank', lambda rows, config: (rows, 0))
    route = {'transport_cost': 100}
    direct = {'buy': {'predicted_price': 100}, 'routes': [route], 'storage_days': 0}
    rows, timing, unavailable = p.candidates(direct, day, None, [])
    assert len(rows) == len(timing) == 1
    assert [row['days'] for row in unavailable] == [7, 14, 30]


@pytest.mark.parametrize('future_price,free_t,winner', [
    (1200, 10, 0), (2400, 10, 7), (1201, 10, 0), (900, 10, 0), (2400, 9.9, 0),
])
def test_integrated_selling_timing_economics(market_prices, monkeypatch, future_price, free_t, winner):
    from Code.intelligence import roads

    now = datetime(2026, 11, 13, 8, tzinfo=IST)
    monkeypatch.setattr(s, 'now_ist', lambda: now)
    for market in market_prices:
        market['target_date'] = now.date().isoformat()
    facility = {'warehouse_id': 'storage', 'name': 'Storage', 'latitude': 21, 'longitude': 75,
                'supported_crops': ['Onion'], 'free_t': free_t, 'max_days': 30,
                'storage_class': 'dry', 'rs_q_day': 2}
    monkeypatch.setattr(s, 'warehouses', lambda: [facility])
    monkeypatch.setattr(s.lg, 'node_warehouse', lambda: None)
    monkeypatch.setattr(roads, 'saved', lambda *args: [])
    monkeypatch.setattr(roads, 'cached_geometry', lambda *args: {
        'geometry': [[20, 75], [21, 75], [22, 75]], 'road_km': 100, 'road_hours': 2,
        'stop_index': 1, 'inbound_hours': 1,
    })
    def forecast(price, horizon):
        return {'kind': 'future_forecast', 'crop': price['crop'], 'series_id': price['series_id'],
                'target_date': (now.date() + timedelta(days=horizon)).isoformat(), 'horizon_days': horizon,
                'price': future_price if horizon == 7 else 1200, 'historical_mae': 120}
    monkeypatch.setattr(p.future, 'forecast', forecast)

    result = s.strategies(buy_id='0', sell_id='2', quantity=100, integrated=True, details=True)
    best = result['groups']['interstate']['best']
    assert best['storage_days'] == winner
    assert best['schedule']['procurement_at'] == now.isoformat()
    assert best['timing_options'][0]['schedule'] == best['schedule']
    options = {row['storage_days']: row for row in best['timing_options']}
    assert options[0]['storage'] == options[0]['storage_loss_pct'] == 0
    if free_t < 10:
        assert set(options) == {0}
        assert [row['days'] for row in best['timing_unavailable']] == [7, 14, 30]
        return
    assert set(options) == {0, 7, 14, 30}
    for days, row in options.items():
        assert row['quantity_q'] == 100
        assert row['storage'] == days * 200
        daily_loss = s.CONFIG['storage']['dry']['daily_loss_pct']
        saleable = 100 * (1 - row['handling_loss_pct'] / 100) * (1 - daily_loss / 100) ** days
        assert row['saleable_q'] == pytest.approx(saleable)
        assert row['sale_revenue'] == pytest.approx(saleable * row['sale_price'], abs=.01)
        assert row['total_cost'] == pytest.approx(sum(row[k] for k in ('procurement', 'transport', 'handling', 'storage')))
        assert row['margin'] == pytest.approx(row['sale_revenue'] - row['total_cost'])
        assert row['sale_quote']['target_date'] == row['schedule']['sale_at'][:10]
    assert options[7]['sale_price'] == future_price
    if winner:
        assert best['route']['stop_index'] == 1
        assert best['warehouse']['warehouse_id'] == 'storage'


def test_integrated_mode_ranks_complete_plans_and_cached_road_cost(market_prices, monkeypatch):
    from Code.intelligence import roads

    monkeypatch.setattr(s, 'warehouses', lambda: [])
    monkeypatch.setattr(roads, 'cached_geometry', lambda *args: {
        'geometry': [[20, 75], [21, 75]], 'road_km': 90, 'road_hours': 2,
        'stop_index': None, 'inbound_hours': 2,
    })
    result = s.strategies(details=True, integrated=True, quantity=180)
    best = result['groups']['interstate']['best']
    assert best['trips'] == 2 and best['route']['km'] == 100
    assert best['transport'] == 3 * 100 * s.CONFIG['vehicles']['Medium truck']['rs_km']
    assert best['route']['geometry'] and best['schedule']['travel_hours'] == 7.2
    assert best['schedule']['sale_at'][:10] == best['sale_quote']['target_date']
    assert best['timing_options'][0]['schedule'] == best['schedule']


def test_explicit_future_purchase_reprices_both_transaction_dates(market_prices, monkeypatch):
    from datetime import timedelta
    from Code.intelligence import roads

    monkeypatch.setattr(s, 'warehouses', lambda: [])
    monkeypatch.setattr(roads, 'cached_geometry', lambda *args: None)
    today = s.now_ist().date()
    result = s.strategies(details=True, integrated=True, purchase_date=today + timedelta(days=3))
    best = result['groups']['interstate']['best']
    assert best['schedule']['procurement_at'][:10] == (today + timedelta(days=3)).isoformat()
    assert best['buy_quote']['target_date'] == best['schedule']['procurement_at'][:10]
    assert best['buy_quote']['kind'] == 'persistence_assumption'
    assert best['sale_quote']['target_date'] == best['schedule']['sale_at'][:10]
    assert round(best['sale_revenue'] - best['total_cost'], 2) == best['margin']


def test_purchase_date_rejects_past_and_dates_beyond_window():
    from fastapi.testclient import TestClient
    from Code.api.main import app
    client = TestClient(app)
    for value in ('2000-01-01', '2100-01-01'):
        assert client.get('/api/v4/strategies', params={'purchase_date': value}).status_code == 422
