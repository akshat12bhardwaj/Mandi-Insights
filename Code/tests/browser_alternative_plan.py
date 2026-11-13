"""Verify current-day procurement and competitor selling options with Chromium."""
from datetime import datetime
from pathlib import Path
import argparse
import re
import tempfile

from playwright.sync_api import expect, sync_playwright
from Code.daily.policy import IST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5173')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 950})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
        page.goto(base + '/?mode=interstate&quantity=100&vehicle=Medium+truck')
        link = page.get_by_role('link', name='Inspect competitor 1')
        expect(link).to_be_visible(timeout=45000)
        expect(page.get_by_role('link', name='Plan purchase date')).to_have_count(0)
        expect(page.locator('input[type=date]')).to_have_count(0)
        truck = page.locator('.mi-route-truck').first
        truck.scroll_into_view_if_needed(timeout=45000)
        expect(truck).to_have_attribute('data-lat', re.compile(r'\d'))
        initial_lat = truck.get_attribute('data-lat')
        expect(truck).not_to_have_attribute('data-lat', initial_lat)
        target = link.get_attribute('href')
        link.scroll_into_view_if_needed()
        scroll = page.evaluate('window.scrollY')
        with page.expect_response(lambda response: '/api/v4/strategies?' in response.url and 'selected_id=' in response.url) as request:
            link.click()
        expect(page).to_have_url(base + target)
        response = request.value
        assert 'purchase_date=' not in response.url
        data = response.json()
        assert data['date'] == datetime.now(IST).date().isoformat()
        assert data['rows'][0]['schedule']['procurement_at'].startswith(data['date'])
        expect(page.locator('input[type=date]')).to_have_count(0)
        expect(page.get_by_text('Current-day estimate', exact=False)).to_be_visible(timeout=45000)
        expect(page.get_by_role('group', name='Estimated margin by sale date')).to_be_visible()
        plan = page.get_by_role('region', name='Journey plan')
        expect(plan).to_be_visible()
        timing = page.get_by_role('region', name='When to sell')
        expect(timing.get_by_text('Recommended timing')).to_have_count(1)
        storage = timing.get_by_role('article').filter(has=page.get_by_role('heading', name='Store 7 days'))
        storage.get_by_role('button', name='Plan this sale').click()
        expect(page).to_have_url(re.compile(r'days=7'))
        expect(plan.get_by_text('Store', exact=True)).to_be_visible()
        finances = page.locator('.mi-financial')
        expect(finances).to_contain_text('Storage · 7 days')
        expect(finances.locator('.mi-financial-totals dd').first).to_have_text(
            storage.locator('dd').last.inner_text()
        )
        expect(page.locator('.mi-map-pin')).to_have_count(3)
        if page.locator('.mi-route-truck').count():
            expect(page.locator('.mi-route-truck')).to_be_visible()
        detail = page.url
        page.reload()
        expect(plan.get_by_text('Store', exact=True)).to_be_visible(timeout=45000)
        page.go_back()
        expect(link).to_be_visible(timeout=45000)
        expect(page.get_by_label('Quantity (quintals)')).to_have_value('100')
        assert abs(page.evaluate('window.scrollY') - scroll) < 100
        page.go_forward()
        expect(page).to_have_url(detail)
        expect(plan.get_by_text('Store', exact=True)).to_be_visible(timeout=45000)
        for width in (390, 360):
            page.set_viewport_size({'width': width, 'height': 844})
            expect(timing).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth') <= width
        page.screenshot(path=str(Path(tempfile.gettempdir()) / 'bda-alternative-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
    print('Passed current IST procurement, competitor selling options, timeline, finances, map, navigation, and 390/360 px.')


if __name__ == '__main__':
    main()
