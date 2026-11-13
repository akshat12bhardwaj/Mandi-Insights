# Markets intelligence — 13 November 2026

Implemented against the existing Mandi Insights application. This is the Markets-only revamp requested in the latest brief; earlier strategy, forecasting and publication work remains in place.

## 1. Markets page

Replaced the very long table with a compact workspace: grouped interactive map, selected-market summary, a ten-row paginated list with its own scroll area, and five focused detail tabs. The beige, white and forest-green styling is preserved. Crop, state, district, market-name, current-forecast and optional price-range filters work together. Context can be hidden. The layout stacks on phones and supports keyboard tab navigation.

Map points represent all filtered mapped series, including those outside the current list page. Selecting such a point loads that exact series without rewriting the search. High-zoom groups sharing one reference open a market chooser. Labels are inserted as text, rather than interpreted as HTML. Historical and unmapped series remain inspectable.

## 2. Context per market

The summary and detail panels expose crop, variety, grade, source, exact reported location identity, current forecast where eligible, latest available observed price/date, up to 60 actual historical reports, first-to-last reported-price change, associated commodity series, modeled weather, sampled geography, relevant trading connections, nearby facilities and a transparent buying/selling/observation insight. Related commodity links retain their own source-series identities.

Historical trends contain reported values only. Missing dates are not filled with fabricated observations. Missing history leaves the rest of the market detail available. Historical prices never become current trade recommendations.

## 3. Terrain and geography

At an accepted market reference, the elevation service samples the center plus four cardinal points approximately 3 km away. It shows the center elevation, a broad elevation band and the sampled elevation range. A range of at least 200 m adds an approach-gradient caution. It does not infer urban/rural land use, coastal/plain/hilly classification, road gradients, flood safety or an exact market entrance.

The source is [Copernicus DEM GLO-90 through Open-Meteo](https://open-meteo.com/en/docs/elevation-api), with an approximately 90 m source grid. These are reference-point approximations, particularly where a market is located only to a district/locality. No accepted coordinate means no geographic lookup or invented location.

## 4. Current and future weather

[Open-Meteo's forecast API](https://open-meteo.com/en/docs) supplies modeled current temperature, humidity, precipitation over the model interval and wind, plus a three-calendar-day temperature/rain/rain-probability outlook. Current modeled conditions are clearly separate from station observations and future daily totals. Null rain remains unavailable, rather than becoming zero.

Weather and elevation load separately from the price/detail request. Weather caches for 3 hours, elevation for 30 days; failures have a 15-minute retry cooldown. Simultaneous requests to the same reference share one fetch in the server process. Provider failures return bounded stale cache when usable (weather up to 2 days, elevation up to 365 days), with explicit stale labels. Current model timestamps beyond 3 hours are suppressed, and past outlook dates are removed. All-null weather does not claim available conditions. Existing `BDA_WEATHER_FORECAST=0` disables weather use. Model values and units are validated; requests use bounded timeouts.

## 5. Roads and access

The terrain/roads tab shows coordinate precision, connection distance, modeled time/freight and the route basis. Directed OSM reference-to-reference routes are distinguished from saved road distances and approximate-distance scenarios. Connections use current, exactly crop/variety/grade/source-compatible destination forecasts. Assumed endpoint access remains explicit. No live closure/traffic coverage or invented approximate-route geometry is claimed.

## 6. Nearby warehouses

Facilities are screened within 100 km straight-line distance of the accepted reference. Displayed journey distance uses a saved directed path where possible, then saved network evidence, otherwise the configured detour approximation. The best five known facilities favor crop compatibility and enough simulated capacity before distance.

Each facility shows storage class, routed/approximate journey distance and time, simulated free tonnes, project charges per quintal/day, the seven-day charge for the default 100-quintal load where supported, and a usefulness note. Charges exclude handling, loss and transport. Links carry both the market and selected facility into warehouse/strategy workflows. Existing storage calculation still checks crop suitability, capacity and permitted duration. A missing facility in the project inventory does not establish that no real warehouse exists.

## 7. Decision engine

Market role derives from existing calculations for both buying here and selling here against current compatible mapped peers with recognized states. It considers procurement, selling price, loss, handling, freight and the existing forecast-error/report-age/price-movement/route-evidence screens. Net margin and adjusted comparison value remain distinct. No feasible positive screened candidate means Observe. The compatible-price median provides context, rather than a new arbitrary score.

Storage support is explained alongside this role; availability alone does not prove that holding is beneficial. Cached weather and terrain annotations now enter strategy shortlist and custom-scenario outputs through `market_context`, with actual caution text also available in `decision.context_notes`. Forecast rain of at least 40 mm/day, modeled wind of at least 50 km/h and sampled elevation range of at least 200 m trigger project operational cautions. They are not official warnings, price multipliers, road closures or automatic rejection rules. Trading requests never fetch external context or train models.

## 8. API and implementation

- `GET /api/v4/market-intelligence?crop=…&series_id=…&quantity=100`: market, observed/forecast price context, related series, logistics, nearby storage, insight and cache-only environmental context.
- `GET /api/v4/market-environment?crop=…&series_id=…`: separately fetched/cached modeled weather and terrain at the accepted reference; explicit unavailable response when unmapped.
- Existing `/markets` retains backward-compatible defaults; the new page requests `limit=10`. Existing daily/history, strategy and warehouse endpoints remain available.
- Detail/environment responses bind to the serving dataset/batch and reject an overlapping publication change. Invalid crop/series/quantity is rejected. Frontend contracts live in `frontend/src/lib/market-intelligence.ts`.
- Core files: `Code/intelligence/market_context.py`, `Code/intelligence/environment.py`, `Code/api/intelligence.py`, `frontend/src/pages/MarketIntelligence.tsx`, the shared map, and the existing strategy/storage explanation hooks.

## 9. Verification

Actual results for this implementation:

- Full safe backend suite: **650 passed, 1 skipped, 1 known failure**, 285.13 seconds. The unchanged frozen D-52 test `test_real_freeze_verifies_without_reading_records` expects an absent evaluation lock despite the already consumed authorized run. Neither the frozen test nor its lock was changed. Three additional regression tests added after this full run are included in the final focused run below.
- Final focused backend run: **64 passed**, 18.07 seconds. Covers market/context contracts, current-vs-historical roles, compatibility and costs, weather units/ranges/nulls/coverage, cache success/failure/concurrency/expiry, defensible elevation sampling, annotation-only integration, warehouse capacity/distance, filtering and missing-data behavior, plus existing intelligence and dynamic-mode/learning tests.
- Frontend: **57 passed**. Includes map selection outside the page, shared-reference chooser, filters/pagination, current-vs-outlook rendering, weather failure, terrain/roads, warehouse handoffs, historical/unmapped/empty states and keyboard tabs.
- TypeScript and production build passed. Existing bundle-size warning remains; chart-container warnings in jsdom remain in older tests.
- Native headless Chromium Markets checks passed with no page errors: live grouped map, pagination, weather/terrain/decision tabs, nearby storage handoff, state/district/current-only/price/context filters, historical/unmapped detail and no horizontal overflow at **900, 390 and 360 px**.
- Existing end-to-end strategy/market/warehouse browser checks also passed. One concurrent run initially exceeded the five-second assertion while the backend suite was active; the isolated rerun passed.
- `git diff --check` passed. No staged changes, commits, pushes, raw-data deletion, protected model artifact modifications or scheduler changes were made by this task.

Commands, from the project root unless indicated:

```powershell
C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider Code/tests
C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider Code/tests/test_market_context.py Code/tests/test_intelligence.py Code/tests/test_dynamic_intelligence.py Code/tests/test_mode_learning.py
C:\Python313\python.exe -B Code/tests/browser_markets.py
C:\Python313\python.exe -B Code/tests/browser_intelligence.py
Set-Location frontend
npm test -- --reporter=dot
npx tsc --noEmit
npm run build
```

Evidence is in `Processed_Data/intelligence_v1/qa/markets-browser.json`, `markets-backend-focused.log`, `markets-frontend-tests.log`, `markets-verification.json`, `markets-intelligence-desktop.png`, `markets-intelligence-mobile.png`, `markets-weather.png` and `markets-terrain-roads.png`.

## 10. Remaining limits

Current forecasts still cover only eligible accepted local series. Many historical markets lack a defensible coordinate. Related series use exact reported names and do not assume a cross-source identity bridge. Weather is an outdoor model at a reference, terrain is a small DEM sample, road distances include assumed access, and facility coverage is incomplete. Warehouse capacity, occupancy, suitability and charges remain project simulations. Market comparisons use a 100-quintal medium truck by default; the strategy workspace supports adjusting the scenario. The global recommendation does not change merely because a market context tab was opened. No major model was retrained or promoted for this revamp.

## 11. Run the app

First PowerShell window:

```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
```

Second PowerShell window:

```powershell
Set-Location '<project-root>\frontend'
npm run dev -- --host 127.0.0.1 --port 5173
```

Open [Markets](http://127.0.0.1:5173/markets). If the daily batch has expired and the scheduled publisher has not run, the existing offline publication command is `C:\Python313\python.exe -B -m Code.intelligence.refresh --batch-only` from the project root. It is not required merely to start the servers.
