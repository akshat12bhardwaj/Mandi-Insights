"""Live browser checks for map discovery, warehouse capacity and strategy routes."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import requests
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5173')
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')

    def get(path, **params):
        response = requests.get(f'{args.api_url}/api/v4/{path}', params=params, timeout=35)
        response.raise_for_status()
        return response.json()

    routed = None
    for candidate in get('strategies', mode='both')['rows']:
        road = candidate['route']
        if road['objective'] != 'approximate' and get('route', origin=road['origin'], destination=road['destination'], objective=road['objective'])['geometry']:
            routed = candidate
            break
    assert routed, 'A current strategy with saved route geometry is needed for this smoke test'
    strategy_url = base + '/?' + urlencode({'crop': routed['crop'], 'buy': routed['buy']['series_id'], 'sell': routed['sell']['series_id']})
    market_name = 'A lot APMC'
    point, = get('market-map', search=market_name)['points']
    facilities = get('warehouses', crop='Wheat')['rows']
    warehouse = next(w for w in facilities if w['warehouse_id'] == 'W:osm:buildings_a:1138073675')
    nearby = get('warehouses/' + warehouse['warehouse_id'] + '/nearby-markets')
    assert nearby['rows']
    warehouse_url = base + '/warehouses?' + urlencode({'facility': warehouse['warehouse_id']})

    with TemporaryDirectory() as temp, sync_playwright() as playwright:
        screenshots = args.screenshots or Path(temp)
        screenshots.mkdir(parents=True, exist_ok=True)
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())

        page.goto(base + '/markets')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='Market map')).to_be_visible()
        expect(page.get_by_role('heading', name='Market directory')).to_have_count(0)
        page.get_by_label('Find a market').fill(market_name)
        marker = page.locator('.mi-map-icon').filter(has=page.locator('svg'))
        expect(marker).to_have_count(1, timeout=30000)
        marker.click()
        expect(page.get_by_role('heading', name=market_name)).to_be_visible(timeout=30000)
        expect(page.get_by_role('region', name='Weather and terrain')).to_be_visible()
        expect(page.locator('.mi-weather-pin').first).to_be_visible(timeout=45000)
        page.get_by_role('button', name='Reported crops').click()
        expect(page.get_by_text('Latest audited report', exact=False)).to_be_visible(timeout=30000)
        page.get_by_label('Find a market').fill('')
        page.get_by_label('Crop', exact=True).select_option('Wheat')
        expect(page.get_by_role('slider')).to_be_visible(timeout=30000)
        page.get_by_role('button', name='Below').click()
        page.get_by_role('slider').press('Home')
        expect(page.locator('.mi-map-pin.muted').first).to_be_visible()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(screenshots / 'markets.png'))

        page.goto(warehouse_url)
        expect(page.get_by_role('heading', name=warehouse['name'])).to_be_visible(timeout=30000)
        expect(page.get_by_text('simulated weekly', exact=False)).to_be_visible()
        expect(page.get_by_role('link', name=nearby['rows'][0]['market']).first).to_be_visible(timeout=30000)
        expect(page.get_by_role('region', name='Weather and terrain')).to_be_visible()
        expect(page.get_by_text('Check shared capacity and storage charges')).to_have_count(0)
        expect(page.locator('.mi-weather-pin').first).to_be_visible(timeout=45000)
        page.get_by_label('Storage type', exact=True).select_option('cold')
        expect(page.get_by_text('Select a warehouse pin to inspect a facility.')).to_be_visible()

        page.goto(strategy_url)
        expect(page.get_by_role('region', name='Journey plan')).to_be_visible(timeout=30000)
        timing = page.get_by_role('region', name='When to sell')
        expect(timing.get_by_role('heading', name='Sell on arrival')).to_be_visible()
        expect(timing.get_by_role('heading', name='Store 30 days')).to_be_visible()
        expect(timing.get_by_text('Recommended timing')).to_be_visible(timeout=45000)
        from urllib.parse import urlparse, parse_qs
        picked = parse_qs(urlparse(strategy_url).query)
        planned = get('strategies', plan='true', mode='auto', crop=picked['crop'][0],
                      buy_id=picked['buy'][0], sell_id=picked['sell'][0])['rows'][0]
        assert planned['schedule']['sale_at'][:10] == planned['sale_quote']['target_date']
        assert round(planned['sale_revenue'] - planned['total_cost'], 2) == planned['margin']
        expect(page.locator('.mi-financial-totals')).to_contain_text('Estimated net margin')
        timing.screenshot(path=str(screenshots / 'selling-timing.png'))
        storage = timing.get_by_role('button', name='Plan this sale').first
        if storage.count():
            storage.click()
            expect(page.get_by_role('region', name='Journey plan').get_by_text('Store', exact=True)).to_be_visible()
            expect(page.get_by_text('Selected selling date', exact=True)).to_be_visible()
            page.get_by_role('button', name='Return to recommendation').click()
        page.get_by_role('region', name='Trade route map').scroll_into_view_if_needed(timeout=45000)
        truck = page.locator('.mi-route-truck')
        expect(truck).to_be_visible(timeout=30000)
        page.wait_for_function('() => Boolean(document.querySelector(".mi-route-truck")?.dataset.lat)')
        initial = truck.evaluate('(el) => [el.dataset.lat, el.dataset.lng]')
        page.wait_for_function('([lat, lng]) => { const point = document.querySelector(".mi-route-truck")?.dataset; return point && (point.lat !== lat || point.lng !== lng) }', arg=initial)
        moved = truck.evaluate('(el) => [el.dataset.lat, el.dataset.lng]')
        assert moved != initial
        print(f'Truck geographic movement: {initial} -> {moved}', flush=True)
        page.screenshot(path=str(screenshots / 'truck.png'))
        page.emulate_media(reduced_motion='reduce')
        expect(truck).to_have_attribute('data-stationary', 'true')
        stationary = truck.evaluate('(el) => [el.dataset.lat, el.dataset.lng]')
        page.wait_for_timeout(350)
        assert truck.evaluate('(el) => [el.dataset.lat, el.dataset.lng]') == stationary
        for label in ('Adjust this scenario', 'Comparison assumptions', 'How opportunities are ranked', 'What could change this recommendation?'):
            expect(page.get_by_text(label, exact=True)).to_have_count(0)
        expect(page.get_by_text('Total estimated cost', exact=True)).to_be_visible()
        alternate = page.get_by_role('button', name='Fastest estimate', exact=False)
        if alternate.count():
            alternate.click()
            expect(alternate).to_have_attribute('aria-pressed', 'true')
            page.emulate_media(reduced_motion='no-preference')
            expect(truck).to_be_visible(timeout=30000)
        page.get_by_role('link', name='Buying market', exact=True).click()
        expect(page.get_by_role('heading', name=routed['buy']['market'], exact=True)).to_be_visible(timeout=30000)
        expect(truck).to_have_count(0)

        # The original screenshot's pair is outside the precomputed route set.
        market_rows = get('markets', crop='Green Chilli', recent=True, limit=200)['rows']
        by_market = {row['market']: row for row in market_rows}
        if {'Warangal APMC', 'Habra APMC'} <= by_market.keys():
            buy, sell = (by_market[name] for name in ('Warangal APMC', 'Habra APMC'))
            page.emulate_media(reduced_motion='no-preference')
            page.goto(base + '/?' + urlencode({'crop': buy['crop'], 'buy': buy['series_id'], 'sell': sell['series_id']}))
            page.get_by_role('region', name='Trade route map').scroll_into_view_if_needed(timeout=45000)
            expect(page.get_by_text('Illustrated road journey · Local OpenStreetMap road graph')).to_be_visible(timeout=360000)
            expect(truck).to_be_visible()
            expect(page.get_by_label('Schematic journey')).to_have_count(0)
            page.screenshot(path=str(screenshots / 'truck-local-road.png'))
            def without_geometry(route):
                response = route.fetch()
                body = response.json()
                for row in body.get('rows', []):
                    row['route'].pop('geometry', None)
                for group in body.get('groups', {}).values():
                    if group['best']:
                        group['best']['route'].pop('geometry', None)
                route.fulfill(response=response, json=body)
            page.route('**/api/v4/strategies?*', without_geometry)
            page.route('**/api/v4/journey-path?*', lambda route: route.fulfill(json={'geometry': None}))
            page.reload()
            expect(page.get_by_label('Schematic journey')).to_be_visible(timeout=30000)
            expect(truck).to_have_count(0)
            page.unroute('**/api/v4/journey-path?*')
            page.unroute('**/api/v4/strategies?*')
        page.get_by_role('navigation', name='Main').get_by_role('link', name='Markets').hover()
        assert page.get_by_role('navigation', name='Main').get_by_role('link', name='Markets').evaluate(
            '(el) => getComputedStyle(el).transitionDuration !== "0s"')

        for width in (820, 390, 360):
            mobile = browser.new_page(viewport={'width': width, 'height': 844}, is_mobile=True, has_touch=True)
            mobile.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            mobile.goto(strategy_url)
            expect(mobile.get_by_role('region', name='Journey plan')).to_be_visible(timeout=30000)
            assert mobile.evaluate('document.documentElement.scrollWidth') <= width
            if width == 390:
                mobile.get_by_role('region', name='Journey plan').screenshot(path=str(screenshots / 'journey-mobile.png'))
            for name, url in [('market', base + '/markets?' + urlencode({'crop': point['crop'], 'series': point['series_id']})), ('warehouse', warehouse_url)]:
                mobile.goto(url)
                expect(mobile.locator('.mi-market-profile h2')).to_be_visible(timeout=30000)
                assert mobile.evaluate('document.documentElement.scrollWidth') <= width, (name, width)
                if width == 390:
                    mobile.screenshot(path=str(screenshots / f'{name}-mobile.png'), full_page=True)
            mobile.close()
        assert not errors, errors
        browser.close()
    print('Passed live market and warehouse map checks, exact market handoff, road-following truck, reduced motion, and 390/360 px layouts.')


if __name__ == '__main__':
    main()
