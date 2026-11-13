"""Published inventory, directional economics and facility-wide preview contracts."""
from fastapi.testclient import TestClient

from Code.api.main import app
from Code.intelligence import market_context, market_inventory, service, warehouse_context
from Code.tests.test_dynamic_intelligence import market_prices  # pytest fixture


def test_market_identity_keeps_district_and_state_boundaries():
    key = market_inventory.market_key
    row = {'state': 'Haryana', 'district': 'Ambala', 'market': 'Example Mandi'}
    assert key(row) == key({**row, 'market': ' EXAMPLE  MANDI '})
    assert key(row) == key({**row, 'state': 'HR'})
    assert key(row) != key({**row, 'district': 'Hisar'})
    assert key(row) != key({**row, 'state': 'Punjab'})


def test_market_inventory_search_sort_pagination_and_forecast(monkeypatch):
    anchor = {'series_id': 'one', 'state': 'Haryana', 'district': 'Ambala', 'market': 'Example',
              'crop': 'Wheat', 'variety': 'Other', 'grade': 'FAQ', 'source': 'datagov',
              'last_observed_price': 2000, 'observation_date': '2026-11-12', 'batch_price': 2020}
    old = {**anchor, 'series_id': 'two', 'crop': 'Onion', 'grade': 'Unspecified',
           'source': 'agmarknet_archive', 'batch_price': None, 'observation_date': '2024-01-01'}
    remote = {**old, 'series_id': 'three', 'district': 'Hisar'}
    locations = {market_inventory.market_key(anchor): [anchor, old], market_inventory.market_key(remote): [remote]}
    monkeypatch.setattr(market_inventory, 'index', lambda: (locations, {r['series_id']: r for r in [anchor, old, remote]}))
    monkeypatch.setattr(market_inventory, 'forecast_is_current', lambda pointer: pointer['current'])
    monkeypatch.setattr(market_inventory.daily, 'snapshot', lambda: (None, None, None, {
        'current': True, 'sha256': 'batch', 'dataset_version': 'release'}))
    client = TestClient(app)
    first = client.get('/api/v4/market-crops?series_id=one&sort=forecast&limit=1').json()
    second = client.get('/api/v4/market-crops?series_id=one&sort=forecast&limit=1&offset=1').json()
    assert first['crop_count'] == first['total_series'] == 2
    assert first['rows'][0]['forecast_ready'] and first['rows'][0]['predicted_price'] == 2020
    assert second['rows'][0]['series_id'] == 'two' and second['rows'][0]['status'] == 'Historical observations'
    assert client.get('/api/v4/market-crops?series_id=one&search=onion+unspecified').json()['total'] == 1
    expired = market_inventory.inventory('one', {'current': False}, sort='latest')
    assert expired['forecast_series'] == 0 and expired['rows'][0]['predicted_price'] is None


def test_market_directions_rank_multiple_compatible_crops(market_prices, monkeypatch):
    locations, by_id, prices = {}, {}, []
    for i, crop in enumerate(('Onion', 'Potato')):
        for j, (name, price) in enumerate((('Here', 4000), ('Cheaper', 2000), ('Dearer', 6000))):
            row = {**market_prices[0], 'crop': crop, 'market': name, 'series_id': f'{i}-{j}',
                   'predicted_modal_price': price}
            prices.append(row)
            by_id[row['series_id']] = row
            locations.setdefault(market_inventory.market_key(row), []).append(row)
    incompatible = {**prices[1], 'series_id': 'bad-grade', 'grade': 'Other', 'predicted_modal_price': 500}
    prices.append(incompatible)
    monkeypatch.setattr(service, 'current_prices', lambda: prices)
    monkeypatch.setattr(market_inventory, 'index', lambda: (locations, by_id))
    monkeypatch.setattr(market_inventory, 'forecast_is_current', lambda _: True)
    monkeypatch.setattr(service.daily, 'error_information', lambda _: {'mae': 10})
    client = TestClient(app)
    buying = client.get('/api/v4/market-opportunities?series_id=0-0&side=buy').json()['rows']
    selling = client.get('/api/v4/market-opportunities?series_id=0-0&side=sell').json()['rows']
    assert {r['crop'] for r in buying} == {r['crop'] for r in selling} == {'Onion', 'Potato'}
    assert all(r['buy_market'] == 'Here' and r['sell_market'] == 'Dearer' for r in buying)
    assert all(r['sell_market'] == 'Here' and r['buy_market'] == 'Cheaper' for r in selling)
    assert all(r['freight'] > 0 and r['handling'] > 0 and r['adjusted_value'] < r['net_margin'] for r in buying + selling)


def test_allocation_is_shared_and_read_only(monkeypatch):
    warehouse = {'warehouse_id': 'w', 'free_t': 350, 'max_days': 30, 'rs_q_day': 0.6,
                 'supported_crops': ['Wheat', 'Rice']}
    monkeypatch.setattr(service, 'warehouses', lambda: [warehouse])
    client = TestClient(app)
    path = '/api/v4/warehouses/w/allocation'
    first = {'crop': 'Wheat', 'quantity_q': 2000, 'days': 7}
    second = {'crop': 'Rice', 'quantity_q': 1600, 'days': 14}
    over = client.post(path, json={'loads': [first, second]}).json()
    assert over['requested_t'] == 360 and not over['fits_together'] and not over['feasible']
    assert all(row['fits_alone'] and row['compatible'] for row in over['rows'])
    assert over['rows'][0]['storage_charge'] == 8400
    exact = client.post(path, json={'loads': [first, {**second, 'quantity_q': 1500}]}).json()
    assert exact['feasible'] and exact['requested_t'] == exact['available_t'] == 350
    unsupported = client.post(path, json={'loads': [{**first, 'crop': 'Onion'}, {**second, 'quantity_q': 100, 'days': 31}]}).json()
    assert not unsupported['feasible'] and unsupported['fits_together']
    assert not unsupported['rows'][0]['compatible'] and not unsupported['rows'][1]['duration_ok']
    assert warehouse['free_t'] == 350
    assert client.post(path, json={'loads': [{**first, 'quantity_q': -1}]}).status_code == 422
    decimal_loads = [{**first, 'quantity_q': 0.1}, {**second, 'quantity_q': 0.2}]
    assert service.allocation({**warehouse, 'free_t': 0.03}, decimal_loads)['feasible']


def test_nearby_markets_preserve_crops_and_road_comparison(monkeypatch):
    row = {'series_id': 'wheat', 'state': 'Haryana', 'district': 'Ambala', 'market': 'Nearby',
           'crop': 'Wheat', 'variety': 'Other', 'grade': 'FAQ', 'source': 'datagov',
           'last_observed_price': 2000, 'observation_date': '2026-11-12', 'batch_price': 2020}
    other = {**row, 'series_id': 'rice', 'crop': 'Rice', 'batch_price': None}
    key = market_inventory.market_key(row)
    location = {'lat': 30, 'lng': 77, 'node': 'A', 'precision': 'District reference'}
    warehouse = {'warehouse_id': 'w', 'latitude': 30.1, 'longitude': 77}
    monkeypatch.setattr(service, 'warehouses', lambda: [warehouse])
    monkeypatch.setattr(service.lg, 'node_warehouse', lambda: None)
    monkeypatch.setattr(market_context.roads, 'saved', lambda *_: [{'road_km': 15, 'road_hours': 0.4}])
    monkeypatch.setattr(market_inventory, 'index', lambda: ({key: [row, other]}, {}))
    monkeypatch.setattr(market_inventory, 'forecast_is_current', lambda _: True)
    monkeypatch.setattr(market_inventory.daily, 'snapshot', lambda: (None, None, None, {'sha256': 'batch', 'dataset_version': 'release'}))
    monkeypatch.setattr(market_inventory.daily, '_signature', lambda: ())
    monkeypatch.setattr(warehouse_context, '_mapped', lambda *_: [(key, location)])
    response = TestClient(app).get('/api/v4/warehouses/w/nearby-markets?crop=Wheat&quantity=120').json()
    nearby, = response['rows']
    assert nearby['reported_crops'] == ['Rice', 'Wheat'] and nearby['predicted_price'] == 2020
    assert nearby['distance_kind'] == 'directed_road' and nearby['distance_km'] == 21
    assert nearby['freight'] == 21 * 35 * 2


def test_warehouse_comparison_has_multiple_horizons_and_simulations(market_prices, monkeypatch):
    warehouse = {'warehouse_id': 'w', 'free_t': 350, 'max_days': 20, 'rs_q_day': 0.6, 'storage_class': 'dry',
                 'supported_crops': ['Onion'], 'latitude': 20, 'longitude': 75}
    monkeypatch.setattr(service, 'warehouses', lambda: [warehouse])
    monkeypatch.setattr(service.lg, 'node_warehouse', lambda: None)
    monkeypatch.setattr(warehouse_context.future, 'forecast', lambda row, days: {
        'price': row['predicted_price'], 'historical_mae': 50})
    client = TestClient(app)
    path = '/api/v4/warehouses/w/opportunities'
    result = client.get(path, params={'series_id': '0', 'limit': 20}).json()
    rows = result['rows']
    assert {r['days'] for r in rows} == {7, 14}
    assert all(r['buy_id'] == '0' and r['sale_kind'] == 'persistence_assumption' and r['freight'] > 0 for r in rows)
    assert all(r['storage'] == 60 * r['days'] and r['margin_difference'] < 0 for r in rows)
    simulated = client.get(path, params={'series_id': '0', 'future_change': 10}).json()['rows']
    assert simulated and all(r['sale_kind'] == 'scenario' and r['future_change'] == 10 for r in simulated)
    assert client.get(path, params={'series_id': 'missing'}).json()['total'] == 0
    assert client.get(path, params={'quantity': 3501}).json()['total'] == 0
    assert client.post('/api/v4/scenario', json={'buy_id': '0', 'sell_id': '1', 'batch_id': 'older'}).status_code == 503
