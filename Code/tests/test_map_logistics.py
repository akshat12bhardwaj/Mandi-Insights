from fastapi.testclient import TestClient

from Code.api.main import app
from Code.intelligence import environment, market_inventory, roads, service, warehouse_context
from Code.tests.test_dynamic_intelligence import market_prices  # pytest fixture


def test_local_route_joins_two_road_legs(monkeypatch):
    import numpy as np
    from scipy.spatial import cKDTree
    from Code.routing import network, pipeline

    graph = network.build_graph([(np.array([[70, 20], [71, 21], [72, 21], [73, 20]]), 'primary', 'B', 0)])
    core = np.arange(len(graph.lat))
    monkeypatch.setattr(roads, '_road_network', lambda: (graph, core, cKDTree(pipeline._xyz(graph.lat, graph.lon))))
    roads._local_geometry.cache_clear()
    try:
        result = roads.local_geometry((20, 70), (20, 73), 'shortest', (21, 72))
        assert result['geometry'] == [[20, 70], [21, 71], [21, 72], [20, 73]]
        assert result['stop_index'] == 2 and result['road_km'] > 300
        assert roads.local_geometry((20, 60), (20, 73), 'shortest')['geometry'] is None
    finally:
        roads._local_geometry.cache_clear()


def test_map_groups_market_identities_and_separates_price_bases(monkeypatch):
    a = {'state': 'Haryana', 'district': 'Sonipat', 'market': 'Example APMC', 'crop': 'Wheat',
         'series_id': 'a', 'batch_price': 2100, 'last_observed_price': 2000, 'observation_date': '2026-11-10'}
    b = {**a, 'market': 'Remote Mandi', 'series_id': 'b', 'last_observed_price': 1000, 'batch_price': None}
    older = {**a, 'series_id': 'old', 'observation_date': '2024-01-01', 'last_observed_price': 800}
    key = market_inventory.market_key(a)
    monkeypatch.setattr(market_inventory, 'index', lambda: ({key: [a, older], market_inventory.market_key(b): [b]}, {}))
    monkeypatch.setattr(market_inventory, 'forecast_is_current', lambda _: True)
    monkeypatch.setattr(market_inventory.daily, '_signature', lambda: ())
    monkeypatch.setattr(warehouse_context, '_mapped', lambda *_: [(key, {'lat': 29, 'lng': 77, 'node': 'D:1'})])
    reported = market_inventory.map_inventory({}, 'Wheat', '', '', 'reported')
    assert reported['bounds'] == [1000, 2000]
    assert [p['series_id'] for p in reported['points']] == ['a']
    assert reported['points'][0]['approximate']
    assert reported['unmapped_count'] == 1 and reported['unmapped'][0]['series_id'] == 'b'
    forecast = market_inventory.map_inventory({}, 'Wheat', '', 'sonipat', 'forecast')
    assert forecast['bounds'] == [2100, 2100] and forecast['unmapped_count'] == 0
    assert market_inventory.map_inventory({}, None, '', 'example', 'reported')['bounds'] is None


def test_map_merges_state_aliases_without_changing_source_labels(monkeypatch):
    base = {'district': 'District', 'crop': 'Wheat', 'batch_price': 2100,
            'last_observed_price': 2000, 'observation_date': '2026-11-10'}
    rows = [{**base, 'state': state, 'series_id': str(i), 'market': f'Market {i}'}
            for i, state in enumerate(['Uttarakhand', 'Uttrakhand', 'Orissa', 'Odisha', 'Keralam', 'Kerala'])]
    locations = {market_inventory.market_key(row): [row] for row in rows}
    monkeypatch.setattr(market_inventory, 'index', lambda: (locations, {}))
    monkeypatch.setattr(market_inventory, 'forecast_is_current', lambda _: True)
    monkeypatch.setattr(market_inventory.daily, '_signature', lambda: ())
    monkeypatch.setattr(warehouse_context, '_mapped', lambda *_: [
        (market_inventory.market_key(row), {'lat': 29, 'lng': 77, 'node': 'D:1'}) for row in rows[::2]])
    for offset, (name, code) in enumerate([('Uttarakhand', 'UK'), ('Odisha', 'OD'), ('Kerala', 'KL')]):
        alias = next(row['state'] for row in rows[2*offset:2*offset+2] if row['state'] != name)
        for state in (name, alias, code):
            result = market_inventory.map_inventory({}, 'Wheat', state, '', 'reported')
            assert result['selected_state_id'] == code
            assert result['states'].count(name) == 1 and alias not in result['states']
            assert result['points'][0]['series_id'] == str(2*offset)
            assert result['unmapped'][0]['series_id'] == str(2*offset+1)
            assert result['unmapped'][0]['label'].endswith(name)
    assert rows[1]['state'] == 'Uttrakhand'


def test_tolls_congestion_loading_and_payload_change_route_selection(market_prices, monkeypatch):
    buy, sell = [{**p, 'predicted_price': p['predicted_modal_price']} for p in market_prices[:2]]
    monkeypatch.setattr(service, 'route_options', lambda a, b: [
        {'km': 100, 'hours': 5, 'objective': 'shortest', 'basis': 'Saved road', 'origin': a, 'destination': b},
        {'km': 120, 'hours': 2, 'objective': 'fastest', 'basis': 'Saved road', 'origin': a, 'destination': b},
    ])
    base = service.calculate(buy, sell, 110, 'Medium truck', 18, 1)
    assert base['trips'] == 2 and base['route']['objective'] == 'shortest'
    assert base['route']['toll_cost'] is None and base['transport'] == 7000
    modeled = service.calculate(buy, sell, 110, 'Medium truck', 18, 1,
                                toll_rs_trip=100, congestion_pct=50, loading_minutes=30, delay_rs_hour=600)
    route = modeled['route']
    assert route['objective'] == 'fastest' and route['hours'] == 3.5
    assert route['base_freight'] == 8400 and route['toll_cost'] == 200 and route['delay_cost'] == 1200
    assert modeled['transport'] == 9800
    assert round(base['margin'] - modeled['margin'], 2) == 2800


def test_route_conditions_use_saved_midpoint_and_endpoints(monkeypatch):
    monkeypatch.setattr(service, 'nodes', lambda: [
        {'node_id': 'A', 'latitude': 20, 'longitude': 70},
        {'node_id': 'B', 'latitude': 20, 'longitude': 74},
    ])
    monkeypatch.setattr(roads, 'geometry', lambda *args: [[20, 70], [20, 72], [20, 74]])
    monkeypatch.setattr(environment, 'context', lambda point, fetch: {'coordinate': point, 'available': False})
    result = TestClient(app).get('/api/v4/route-conditions?origin=A&destination=B&objective=fastest')
    assert result.status_code == 200
    rows = result.json()['samples']
    assert [r['name'] for r in rows] == ['Origin', 'Mid-route', 'Destination']
    assert rows[1]['coordinate']['lng'] == 72
    assert not any(r['available'] for r in rows)
