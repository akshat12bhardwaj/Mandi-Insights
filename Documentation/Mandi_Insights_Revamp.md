# Mandi Insights implementation report — 12 November 2026

**Current Phase 2 result: 239 forecasts across Onion, Potato, Wheat and Tomato; 1,090 trade scenarios.** The Phase 2 section at the end contains the latest measured coverage, tests, limits and scheduler instructions. The sections immediately below preserve the Phase 1 implementation snapshot; their older counts are superseded by Phase 2.

## Application and implementation

- `/` opens Strategies: automatic opportunities, crop and purchase-state filters, quantity and vehicle selection, a six-card shortlist, selectable comparisons, road map and complete cost breakdown.
- `/markets` provides twenty-crop discovery, state/district/name/price/recent-activity filtering, pagination, grouped map markers, observed trends, optional weather and market comparisons. Buy/sell links carry the selected crop and series into Strategies.
- `/warehouses` displays 168 existing OSM identities, simulated utilization, compatible storage types, capacity/charge/region filters, comparisons and a warehouse-to-strategy handoff.
- About & Data links to retained research and original source views. Old pipelines, APIs, experiments and notebooks remain available. No commit, push, reset, raw-data deletion or protected artifact replacement was performed.
- New implementation: `Code/intelligence/`, `Code/api/intelligence.py`, `frontend/src/pages/Intelligence.tsx`, and `frontend/src/lib/intelligence.ts`. `/api/v4/*` contracts integrate the existing FastAPI application.
- The design retains off-white `#f6f4ee`, white cards, forest green `#1f5c43`, ink `#1c2a23`, muted text `#5b6761` and subtle borders `#e3e0d6`. Trebuchet display typography introduces the recommendation workspace; existing sans typography carries controls and figures. The trade detail and route are the principal visual focus. Mobile controls and navigation stack without horizontal overflow.

## Twenty-crop selection

Onion; Potato; Tomato; Green Chilli; Brinjal; Cauliflower; Cabbage; Wheat; Banana; Cucumbar(Kheera); Paddy(Dhan)(Common); Pumpkin; Carrot; Bottle gourd; Apple; Ginger(Green); Rice; Bhindi(Ladies Finger); Raddish; Bitter gourd.

The reproducible selector reads the existing 56-candidate quality audit, requires at least ten historically daily-eligible market series, and ranks by eligible series, 365-observation series and usable record count, with crop-name tie breaking. It uses **no category quotas**. All three original crops qualify naturally. Source hashes, coverage and selection details are in `Processed_Data/intelligence_v1/catalog.json`. The earlier quota-based daily catalog is unchanged; a new operational release references the new selection.

Historical eligibility is not current forecasting eligibility. The published operational registry contains 69,967 source-separated market/variety series; 208 have current forecasts on the recorded date. Archive and recent reporting identities are not merged without verified mappings.

## Sources and forecasting

- Existing local AGMARKNET commodity archives and the data.gov.in/DMI incremental observations supply prices; no additional raw price download was run during this implementation. New daily publication used existing local observations.
- Existing district arrivals and APY production outputs supply clearly dated historical context for the original three crops. Production values stay at or before agricultural year 2018–19; they are not described as measured current supply.
- Saved OpenStreetMap/Geofabrik facility and road outputs supply identities, coordinates and road geometry. District points are approximate market references, not verified mandi entrances. Markets lacking a reference remain in the list without invented pins.
- Open-Meteo supplies optional outdoor weather with the existing cache. Weather does not alter price predictions.
- [CWC regional offices](https://cewacor.in/CWCRegionalOffices) and [DFPD/WDRA](https://dfpd.gov.in/warehousing-development-regulatory-authority/en) were reviewed as official directory sources. No new facility rows were accepted without reliable coordinates; the existing 168 facilities were retained.
- [NABARD onion storage guidance](https://www.nabard.org/auth/writereaddata/ModelBankProject/2009165817Model_SchemeforOnionStorage.pdf), [NHB potato cold-store standards](https://nhb.gov.in/documents/cs1.pdf) and [2025 cold-chain guidelines](https://nhb.gov.in/guideline/ENGINEERINGGUIDELINES2025.pdf) inform the representative storage classes. Numerical rates and capacities are explicitly project assumptions, not official tariffs or quoted standards.

The operational daily model uses the last valid positive price known at issuance and strictly before the target date. It requires 180 observations, a 365-day span, at least 60 recent observations and 25% recent-year reporting density. Observations older than seven days receive no current prediction. Today's observed price is not used to predict today. Expired batches are unavailable rather than relabeled as current forecasts. Training never runs inside an API request.

## New evaluation actually executed

`python -B -m Code.intelligence.build --evaluate` trained Ridge and HistGradientBoosting candidates for all twenty selected crops and compared them with persistence, exact seven-day seasonal naive and seven-observation moving-average baselines. Training ends in 2016; development evaluation covers 2017–2018, with an explicitly assumed three-day reporting delay, weekly target schedule and up to twelve training-selected series per crop. No protected 2019+ evaluation targets were scored. This is retrospective development evidence, not prospective validation.

Across 15,148 matched targets, persistence MAE ranges from ₹49.32/quintal for Paddy to ₹601.81 for Apple. For the currently forecastable crops, MAE is Onion ₹110.29, Potato ₹67.95 and Wheat ₹76.23/quintal. HistGradientBoosting is worse than persistence for Onion and Potato by 7.40% each, but improves Wheat MAE by 9.35%. Persistence is best among the compared methods for thirteen crops, HistGradientBoosting for five, and moving average for two. Neither Ridge nor seasonal naive wins a crop. Persistence remains operational; learned candidates were fitted for evaluation, not deployed or serialized as serving models. Per-crop results, coverage and protocol are saved in `Processed_Data/intelligence_v1/development/`.

Arrivals and weather were not promoted as price predictors: matched publication-vintage evidence is missing, and the existing negative findings remain intact. Historical production is context only. No new claim of predictive benefit is made.

## Economics, routes and simulation

The engine enumerates compatible mapped current forecast pairs across states and within states (510 pairs in the recorded batch). It requires matching crop, variety, grade and source. Rankings use net margin minus twice historical crop MAE times quantity. Scenarios within ₹100 or 1% of the leading adjusted margin prefer shorter distance. This is a conservative comparison screen, not a calibrated uncertainty interval or a global allocation optimum.

Procurement = buying price × quantity. Revenue = selling price × quantity × (1 − handling-loss fraction). Total expense = procurement + transport + one combined loading/unloading charge + storage. Net margin = revenue − expense. Costs are shown without double-counting handling or storage. Quantity uses quintals; facility space uses tonnes, converted at ten quintals per tonne.

Representative truck assumptions are 40/100/160 quintals at ₹22/35/48 per vehicle-km. Trips = ceiling(quantity/payload). Freight = distance × rate × trips. Handling defaults to ₹18/quintal and handling loss to 1%. The scenario panel allows changing vehicle, quantity, freight rate, payload, handling, loss, regions, markets, storage duration, facility, route and future-price assumption.

Direct comparisons reuse saved shortest/fastest OSM road distances and paths, adding an explicitly assumed 5 km access allowance at each endpoint. Travel time uses saved speeds plus estimated local access. Where saved routes are unavailable, a great-circle distance × 1.3 scenario is labeled approximate and no road line is fabricated. Warehouse detours currently use approximate two-leg distance, not verified facility-access routing. Routes are cached in process.

Warehouse simulation hashes a stable facility ID, assigns a representative dry/ventilated/cold class and nominal size where unknown, and produces 35/50/65/75/90% occupancy bands with bounded small weekly changes. Total − occupied = free capacity. Crops enter only compatible simulated classes; capacity shortages and excessive storage durations are rejected. Dry/ventilated/cold charges default to ₹0.60/1.20/3 per quintal-day; nominal bases are 2,500/500/1,500 tonnes, with deterministic size multipliers. All assumptions live in `Code/intelligence/config.json`.

Storage-then-sale uses an explicitly adjustable future-price change from today's forecast, labeled as a scenario rather than a future forecast. Storage is available through the scenario editor; automatic daily ranking currently compares direct same-day trades only.

## Verification actually run

- Full backend suite: **557 passed, 1 skipped, 1 known failure**, 261.83 seconds. The existing frozen `test_real_freeze_verifies_without_reading_records` expects no D-52 run lock, although the authorized evaluation already consumed that window. Neither its frozen test nor its lock was changed.
- Focused final operational suite: **79 passed** (daily forecasts, refresh/revisions, weather context, trading/decisions and twelve new intelligence tests).
- Frontend Vitest: **37 passed across four files**, including new quota-free crop selection, filter, handoff, missing-data and structured-error checks. Old component regressions run against retained historical subviews.
- Production TypeScript/Vite build passed. Vite reports an initial-bundle size warning; code splitting remains a performance improvement.
- Native Python Playwright/Chromium browser checks passed for default strategies, twenty crop options, scenario comparisons, 250-quintal/three-trip recalculation, markets and warehouse filters, cross-page buy/storage handoffs, future-price storage scenarios, missing forecasts, mobile menu and overflow. Screenshots and browser check results are in `Processed_Data/intelligence_v1/qa/`.
- Repository-local frontend-design and webapp-testing instructions were read and applied. Browser testing followed their rendered-DOM reconnaissance and headless Python Playwright workflow.

## Remaining work

1. Obtain sufficient recent market-level history for the other seventeen crops. Seven days of new collection cannot satisfy a year-long eligibility rule; the application intentionally does not invent those forecasts.
2. Expand verified facility and mandi geocoding. Current maps use approximate district references for markets, and nearest-project-reference regions for warehouses. The facility source is concentrated in Kerala and nearby regions and is not an exhaustive national register.
3. Add verified market–warehouse–market road legs, live availability/charges, crop-specific cold-room settings and real freight quotations. Current assumptions are suitable for a demonstration, not verified operating facts.
4. Add validated future-price forecasts before automatically ranking storage-for-profit trades. Current storage revenue remains an explicit scenario.
5. Distance-from-procurement filters, district-level warehouse filtering, automatic overnight scheduling, allocation across multiple markets, and persisted inventory reservations are not implemented. Manual bounded refresh is implemented. Settings are per scenario, not persisted across browser sessions.
6. Arrivals/production integration covers historical context for the original three crops, not current supply or all twenty crops. Weather is optional and remains secondary.

## Exact Windows PowerShell commands

From the repository root, first rebuild only the operational daily batch (no network):

```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -B -m Code.intelligence.refresh --batch-only
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
Set-Location '<project-root>\frontend'
npm run dev -- --host 127.0.0.1 --port 5173
```

Open the Vite URL printed in that window. If 5173 is already occupied, Vite selects another port. During verification an existing API was already listening on 8000 and the additional verification frontend ran on 5174. No existing user server was stopped.

For manual incremental collection and publication using the existing configured data.gov.in credential (default execution is an offline plan):

```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -B -m Code.intelligence.refresh
C:\Python313\python.exe -B -m Code.intelligence.refresh --execute --lookback-days 7 --budget 280
```

The bounded collector preserves immutable raw vintages and uses the existing publisher lock/rollback safeguards. It does not install a scheduler. Repeat catalog generation with `C:\Python313\python.exe -B -m Code.intelligence.build`; add `--evaluate` only when deliberately rerunning the separate development study. Avoid old `Code.daily build` for the revamped catalog because that older command retains the earlier quota-based selection.

To repeat browser verification against running servers (use Vite's actual port):

```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -m pip install playwright
C:\Python313\python.exe -m playwright install chromium
C:\Python313\python.exe Code/tests/browser_intelligence.py --base-url http://127.0.0.1:5173
```

## Phase 2 — operational expansion (current results, 12 November 2026)
Current results supersede the earlier Phase 1 counts above. **Four crops have 239 current forecasts**, up from three crops and 208 forecasts. Tomato contributes 31 newly eligible series. Eligibility thresholds were not relaxed. The main objective is **partial**, not 20/20 complete.
### Per-crop measured coverage
The complete machine-readable table is `Processed_Data/intelligence_v1/phase2/coverage.csv`; its companion JSON also records historical record counts, 365-day reporting gaps, continuity, geography, status counts and ineligibility reasons. All serving selections below use **persistence**.
- **Onion**: 61 forecasts; 400,366 recent-source records; latest observation 2026-11-11; 30 recent states.
- **Potato**: 74 forecasts; 416,662 recent-source records; latest observation 2026-11-11; 29 recent states.
- **Tomato**: 31 forecasts; 158,911 recent-source records; latest observation 2026-11-11; 29 recent states.
- **Green Chilli**: 0 forecasts; 831 recent-source records; latest observation 2026-11-11; 25 recent states.
- **Brinjal**: 0 forecasts; 1,036 recent-source records; latest observation 2026-11-11; 25 recent states.
- **Cauliflower**: 0 forecasts; 696 recent-source records; latest observation 2026-11-11; 23 recent states.
- **Cabbage**: 0 forecasts; 703 recent-source records; latest observation 2026-11-11; 24 recent states.
- **Wheat**: 73 forecasts; 483,488 recent-source records; latest observation 2026-11-11; 16 recent states.
- **Banana**: 0 forecasts; 895 recent-source records; latest observation 2026-11-11; 24 recent states.
- **Cucumbar(Kheera)**: 0 forecasts; 574 recent-source records; latest observation 2026-11-11; 24 recent states.
- **Paddy(Dhan)(Common)**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.
- **Pumpkin**: 0 forecasts; 619 recent-source records; latest observation 2026-11-11; 22 recent states.
- **Carrot**: 0 forecasts; 554 recent-source records; latest observation 2026-11-11; 21 recent states.
- **Bottle gourd**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.
- **Apple**: 0 forecasts; 285 recent-source records; latest observation 2026-11-11; 19 recent states.
- **Ginger(Green)**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.
- **Rice**: 0 forecasts; 100 recent-source records; latest observation 2026-11-11; 11 recent states.
- **Bhindi(Ladies Finger)**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.
- **Raddish**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.
- **Bitter gourd**: 0 forecasts; 0 recent-source records; latest observation 2024-02-02; 0 recent states.

### Completed implementation
- Added an immutable, paginated collector with two complete-response checks, bounded retries/backoff, request/byte ledgers, shared HTTP sessions, record/unit/date validation, resumable backfills, late-report rechecks and explicit HTTP 429 cooldown. Conflicting price identities go through the existing cleaner instead of rejecting an entire reporting day. Incomplete pages are never published.
- Fixed the verified live-feed alias `Paddy(Common)` → catalog `Paddy(Dhan)(Common)` without merging rice or basmati. The old query returned zero records; the matching query returned 379 in the small sample. The Bottle gourd sample returned 292 records. These samples demonstrate source availability; they are not falsely counted as accepted complete history.
- Expanded Tomato usable recent history from 1,047 to **158,911** records across 29 states and 461 districts, with a maximum 226 observations per series and a 365-day span. The accepted data covers 227 distinct reporting days in the preceding year; 138 days remain uncollected or unreported at crop level. These are crop-level day counts, not individual-market continuity.
- The priority backfill used 521 accounted calls and about 150.04 MB across resumed attempts. Accepted complete partitions were published when the download allowance was reached. A stream read could exceed the allowance by one small chunk in that run; the collector was corrected and tested to cap each subsequent read at the exact remaining byte allowance. No incomplete final response was accepted.
- Retained source observations and retrieval vintages in the existing independently versioned daily release. `operational_view.json` records the logical schema, source hashes, registry and optional covariates. Arrivals/weather/production remain unavailable as validated daily model features; they are not imputed or silently used.
- Added **23** GeoNames/Open-Meteo locality references using exact country, state and locality matching; ambiguous results are rejected. These are approximate references, not verified mandi entrances. The matching and coordinate fields follow the [official Open-Meteo geocoding documentation](https://open-meteo.com/en/docs/geocoding-api). Current trade enumeration produces **1,090** compatible scenarios, including **38 Tomato scenarios**. Crop-specific handling-loss assumptions are centralized and editable per scenario.
- Reused 278 existing reference-to-warehouse links for 93 facilities where both storage legs exist; the reverse leg explicitly assumes symmetric access. Other detours remain approximate, with no fabricated road geometry. The scenario view now compares direct-delivery and storage-scenario margins. Capacity and crop-suitability constraints remain enforced.
- Added a compact refresh timestamp and delayed-source indicator; crop coverage expands to per-crop current counts. Source dependency signatures invalidate API snapshots across processes, and default strategies are precomputed with batch/config/geocoding signatures. A Leaflet navigation/unmount race discovered during the final browser run was fixed and verified.
- Daily orchestration records sanitized JSONL logs, last-success/attempt state, latest observation, new record count, forecast/crop/strategy counts and failures. It supports partial collection, atomic pointer rollback, live-process locks and verified dead-process lock recovery. Running publication twice on unchanged data does not rebuild a current batch.

### Forecast evaluation and artifacts
New fitted Ridge and HistGradientBoosting candidates for all twenty crops are saved in `phase2/models-v1/`, alongside persistence/seasonal/moving-average comparisons, feature names, source hashes, supported series, training cutoff and year/quarter/market/freshness breakdowns. The fixed retrospective study trains through 2016 and evaluates 2017–2018 with an explicitly assumed three-day reporting delay. It uses 15,148 matched targets and never scores protected 2019+ evaluation windows.
Persistence MAE is Onion ₹110.29, Potato ₹67.95, Wheat ₹76.23 and Tomato ₹221.41/quintal. All-crop persistence MAE ranges from ₹49.32 to ₹601.81/quintal. HistGradientBoosting improves Wheat MAE by 8.89% in 2017 and 10.18% in 2018; it is worse for Onion and Potato in both years. Persistence remains the serving choice for every crop because these older revised-archive simulations do not establish current-regime learned-model benefit. Fitted candidates are saved, not silently promoted. Full numerical results are in `models-v1/metrics.csv` and `breakdowns.csv`.

### Partial and externally blocked work
- Sixteen crops still lack sufficient accepted recent market-series history. Ten have only one or two collected recent dates; six still have no accepted recent-source observations. Paddy and Bottle gourd samples confirmed source availability, but the rate-limited bulk refresh did not reach their acceptance step. The per-crop table above is the authoritative current state. More bounded backfills are required; the public source is not declared unavailable merely because history has not yet been collected.
- The subsequent three-day all-crop refresh hit **HTTP 429**, after eleven calls, and retained accepted data and the valid batch. No Retry-After header was supplied; a conservative one-hour cooldown was recorded. No further data.gov.in requests were made during that cooldown. A zero-record current-day response remains missing data, never a zero price.
- The official AGMARKNET 2.0 metadata was accessible and lists 4,178 market identities, but has no market coordinates. Its report endpoint returned HTTP 400 with `TOKEN_OR_CAPTCHA_REQUIRED`. No CAPTCHA/authentication bypass or bulk report collection was attempted. Data.gov.in remains the accepted price source; GeoNames via Open-Meteo is the newly integrated location source.
- Validated future selling-price models, current arrivals/production predictors, exact mandi entrances and verified warehouse reverse-leg geometry remain incomplete. Storage revenue uses an explicit scenario assumption; it is not a future forecast.

### Scheduler status
Windows was verified as **India Standard Time** with Task Scheduler commands available. `install_scheduler.ps1 -ValidateOnly` successfully constructed the action, trigger, principal and settings. **No persistent scheduled task was registered**. Default 22:30 IST is a project choice after the reporting day, not an official source publication promise. The definition uses the current interactive user, correct working directory, missed-run catch-up, three 20-minute restart attempts, a two-hour execution limit and no overlapping task instances. It runs while that user is logged in. Application cooldown/locks also apply to scheduler retries.

### Tests actually executed
- Full safe backend run: **580 passed, 1 skipped, 1 previously documented frozen-test failure** in 478.80 seconds. The failure is the unchanged D-52 pre-run-lock expectation; neither its lock nor its protected test was altered. Additional Phase 2 tests added later are included in the focused result below.
- Final focused suite: **97 passed** across ingestion, refresh, forecast boundaries, scenarios, geocoding, simulation and automation tests. Frontend: **37 passed**. TypeScript and production Vite build passed; the existing bundle-size warning remains. Headless Python Playwright passed all three sections, cross-page handoffs, fractional crop-loss inputs, direct/storage comparison, new Tomato strategies, missing Bitter gourd forecasts, maps and mobile navigation/overflow.

### Current PowerShell commands
```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -B -m Code.intelligence.refresh --batch-only
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
```
```powershell
# Second window
Set-Location '<project-root>\frontend'
npm run dev -- --host 127.0.0.1 --port 5173
```
```powershell
# From the project root: plan, then manual incremental execution
powershell -NoProfile -ExecutionPolicy Bypass -File Code/intelligence/run_refresh.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File Code/intelligence/run_refresh.ps1 -Execute
# Resume a bounded priority backfill after provider cooldown
C:\Python313\python.exe -B -m Code.intelligence.refresh --execute --backfill --lookback-days 366 --crop Tomato --budget 800 --max-mb 150
# Coverage, model artifacts, and browser verification
C:\Python313\python.exe -B -m Code.intelligence.coverage
C:\Python313\python.exe -B -m Code.intelligence.models
C:\Python313\python.exe Code/tests/browser_intelligence.py --base-url http://127.0.0.1:5173
# Validate only: no registration
powershell -NoProfile -ExecutionPolicy Bypass -File Code/intelligence/install_scheduler.ps1 -ValidateOnly
```
The scheduler installer registers a task only when the user deliberately runs it with `-Install`. That action was not taken. For a new backfill allowance, choose a new explicit budget or smaller scope; an exhausted scope cannot silently reset its ledger.

## Phase 3 — decision engine and future selling (13 November 2026)

This section supersedes Phase 2's scheduler, future-price and directed-routing limitations. Historical counts above remain a dated record. All twenty crops remain available for historical exploration. Current eligibility thresholds remain unchanged; observed prices, provider identities and original retrieval vintages are preserved. No frozen research evaluation was rerun, and no code was staged, committed or pushed.

### Final crop and data coverage

The completed **13 November** publication has **254 current forecasts across five crops**, **762 future horizon quotes** and **1,098 compatible trading scenarios**. Per-crop current counts are **Onion 61, Potato 74, Wheat 73, Tomato 31 and Green Chilli 15**. This adds fifteen current forecasts, forty-five future quotes and eight compatible scenarios over the task's starting state. Green Chilli is newly forecastable; the full twenty-crop current forecasting objective remains partial.

Green Chilli collection now contains **116,759 raw records across 204 accepted crop-date partitions**, of which **115,859 are usable recent-source observations**, across **29 states and 418 districts**. There are **114,966 records and 200 distinct crop-reporting days in the preceding 365 days**; individual-market continuity is lower. Maximum per-series measurements are **199 observations and a 371-day span**. Only fifteen series satisfy all unchanged current eligibility checks. The most recent usable source date is **11 November**; empty responses for later dates were retained as missing reports, never zero prices.

The resumed main backfill added **105,556 new raw records** in **362 requests / 90 MB**, accepting 180 complete crop-date partitions. A distinct small extension to the older boundary added **1,106 raw records** in **5 requests / 1 MB**, accepting two complete partitions, including 6 November 2025. This improved the span evidence rather than relaxing the 365-day requirement. Including the earlier forty-request attempt, total Phase 3 source accounting is **407 requests / 99,138,873 bytes (99.14 MB)**, within the overall **450-request / 100-MB allowance**. The earlier attempt stopped on HTTP 429 and its one-hour pause was respected; resumed attempts had no further 429 or retries. Collection stopped exactly at its byte allowances, discarded the incomplete final response, and successfully published the valid complete partitions. A `partial_update` status here describes budget-limited collection, not an invalid published batch. Source ledgers/checkpoints remain resumable.

The remaining fifteen crops are Brinjal, Cauliflower, Cabbage, Banana, Cucumbar(Kheera), Paddy(Dhan)(Common), Pumpkin, Carrot, Bottle gourd, Apple, Ginger(Green), Rice, Bhindi(Ladies Finger), Raddish and Bitter gourd. They retain historical exploration and require more accepted recent history. `phase2/coverage.csv` contains all twenty crop measurements and ineligibility reasons; `phase3/collection_priority.json` was rebuilt after publication and now prioritizes **Brinjal**. No additional bulk source collection was started beyond the allowance.

### Recommendation and interface

Strategies now rank economic margin after explicit comparison reserves for historical forecast error, measured recent price movement, report age and approximate/symmetric logistics. These reserves screen choices; they are not billed expenses, confidence intervals or guaranteed downside bounds. Recent movement uses the 80th percentile of absolute changes across the last thirty actual reporting steps available at the parent forecast issue. It does not imply daily reporting or daily volatility. Similar scores within the larger of ₹100 and 1% of the leading adjusted value prefer supported road paths, shorter distances and fewer trips. The configurable policy is in `Code/intelligence/config.json`.

The first visible recommendation contains an ordered buy → transport → optional store → sell journey, quantity, truck use, net margin and three evidence cards. A compact comparison shows up to two compatible alternatives with actual economic differences; the explanation can favor a lower-margin option when the alternative has larger measured uncertainty deductions. No weather, arrivals or production cause is invented. Expandable details show adjusted value, reserves and the break-even selling price. Custom edits are labeled as the user's scenario rather than a new global optimum.

The shortlist is reduced to three cards. The map, expense breakdown and detailed controls remain available below it. Crop, region, markets, quantity, truck, route, storage and manual price changes remain interactive. A separate selling-date comparison uses actual future baseline quotes; changing its input assumptions hides stale results until recalculation. Stored forecast results retain their forecast label throughout the journey and detail panel. Desktop and mobile styling retains the beige, white and forest-green theme.

### Separate future-price study and storage decisions

`Code/intelligence/future.py` creates a new `phase3/future_v1` study, without modifying Phase 8, candidate protocols or consumed evaluation windows. Its cohort contains at most twelve markets per crop, selected from pre-2017 reporting continuity. It trains on targets through **2016-12-28**, selects on **2017**, confirms on **2018**, and never reads/scores 2019+ targets. Features use an assumed three-day reporting delay. Future labels require an exact observed price on the target date; there is no calendar interpolation. The annual seasonal baseline uses target minus 364 days only when that observation precedes the issue cutoff.

All **60 crop × horizon cells** were evaluated against persistence, annual seasonal persistence, moving average, Ridge and HistGradientBoosting: **300 aggregate model scores**, plus year, season, market and freshness breakdowns. Sixty separately saved model artifacts contain the two fitted learned candidates. Their checksums and the metric checksum are recorded in the manifest. Training remains outside API requests, and an existing study is retained rather than overwritten.

Persistence MAE in INR/quintal on the matched **2017–2018 revised-archive simulations**:

- Onion: **188.88 / 241.65 / 358.96** for 7 / 14 / 30 days; 839 / 816 / 706 validation rows.
- Potato: **85.87 / 99.80 / 158.64**; 866 / 838 / 798 rows.
- Wheat: **76.57 / 78.83 / 103.98**; 434 / 425 / 426 rows.
- Tomato: **382.43 / 523.13 / 775.27**; 883 / 859 / 730 rows.
- Green Chilli: **463.54 / 570.40 / 725.21**; 710 / 700 / 658 rows. Its separately evaluated current-day persistence MAE is **₹331.84/quintal** on 839 historical simulated targets.

These are historical errors, not measured accuracy on today's markets or calibrated confidence. Persistence remains the serving choice because older revised-archive experiments do not establish a current-regime benefit for a learned replacement. Daily publication produces three horizon quotes per currently eligible series, and `/api/v4/future-price` exposes their model, horizon, issue, source observation and evaluation scope. A zero-change persistence forecast is a valid forecast; a manually entered change remains a separate simulation.

`/api/v4/storage-options` compares direct sale against 7/14/30 days using up to three compatible warehouses nearest to the two endpoints combined with sufficient simulated capacity and permitted storage duration. It selects by adjusted economic value within that candidate set, without claiming a national optimum. Costs include both travel legs, truck trips, storage fees, **₹6/quintal extra warehouse handling**, and compound storage shrinkage in addition to the editable handling loss. Daily modeled shrinkage is **0.015% dry, 0.2% ventilated and 0.08% cold**. These are centralized project assumptions, not verified tariffs or measured losses. Forecast mode uses the scheduled selling date and labels carried-forward prices when an exact quote is unavailable. With unchanged future prices, immediate sale normally wins after storage expenses and losses; the system does not invent a price rise to justify storage.

### Agricultural-factor evaluation

`Code/intelligence/factors.py` saves a new matched complete-case study in `phase3/factors_v1` for Onion, Potato and Wheat. Price-only, price + lagged arrivals, and price + arrivals + lagged production use the same observed target cohort, chronological 2017/2018 validation and at most twelve preselected historical markets per crop. Nine model artifacts each contain fitted Ridge and HistGradientBoosting candidates. Metrics and breakdowns include MAE, RMSE and relative skill versus persistence.

For HistGradientBoosting, skill versus persistence for price-only / + arrivals / + production was **−8.59% / −7.66% / −5.78% Onion**, **−5.23% / −12.58% / −14.43% Potato**, and **+9.47% / +8.39% / +7.69% Wheat**. Negative skill means worse than persistence. Arrivals and production did not improve the strongest price-only candidate in this matched comparison. No exogenous model was promoted.

Historical production uses the existing two-agricultural-year lag assumption; that does not prove the original publication vintage. Weather is explicitly excluded where original availability timestamps are missing. The operational daily feed still lacks validated arrivals and production covariates, so current outdoor weather and dated supply context remain explanatory context with no price adjustment. No historical publication time or current supply quantity is fabricated.

### Geographic and warehouse improvements

The new local routing build reuses pinned OpenStreetMap roads rather than downloading another graph. The graph contains **23,127,157 vertices and 44,084,125 directed edges**. The operational cache contains **544 directed shortest/fastest options for 17 endpoints**, including four existing warehouse facilities and leading market references. It supports market → market, market → warehouse and warehouse → market paths with actual simplified geometry, distance, modeled time, source snapshot and file-integrity checks. New inbound and outbound storage legs are computed separately; reverse access is not inferred from the forward path.

When the new directed cache cannot serve both legs, existing reference-to-warehouse links retain their explicit symmetric-access label, and unsupported journeys remain approximate distance scenarios. Local access distances, speed assumptions and freight remain modeled. Road paths between district/locality references do not establish exact facility entrances. The cache deliberately covers a finite set of useful endpoints; it is not all-market routing.

Conservative OSM market matching required an explicit market/mandi/APMC label, an exact normalized core name, a unique OSM identity and a point within thirty kilometers of the existing district/locality reference. Five candidate POIs produced **one accepted market match and 171 rejected identities**: **Gudimalkapur APMC, Hyderabad, Telangana**, OSM 8315262230, at **17.3835626, 78.4353476**. It is a reported OSM market point, not a verified entrance. The other markets retain identified district/locality precision. This precise point is outside the seventeen-endpoint cache and therefore does not silently inherit a district route.

The **168 existing OSM-reported warehouses** are retained. Their coordinates are reported points/outline centroids, and capacity, occupancy, crop compatibility, charges and loss assumptions remain explicitly deterministic project simulations. The implementation improves directed travel, suitability, capacity enforcement and cost comparison without claiming to have surveyed facilities or verified their cold-room settings.

### Automatic operation

Windows **MandiInsightsDailyRefresh is registered and Ready** under the current user's limited interactive account. Its next verified trigger is **13 November 2026 at 22:30 IST**, recurring daily while that user is logged in. The action uses `C:\Python313\python.exe`, the project root as its working directory, a seven-day late-report refresh and limits of **280 requests / 50 MB per scheduled scope**. Registration succeeded without elevation or permission changes. `phase3/scheduler_receipt.json` records the inspected action and next run. Registration and definition were verified; the first automatic invocation has not yet occurred.

Missed-run catch-up, no overlapping task instances, three twenty-minute restart attempts, a two-hour execution limit, structured JSONL logs, shared provider cooldown and resumable source ledgers remain enabled. Valid complete partitions are retained when a source allowance or rate limit stops collection; incomplete responses are never accepted. Last-success publication is preserved on failure. Daily publication updates current quotes, future baseline quotes, quality profiles, coverage and precomputed strategies; API caches follow their dataset/configuration signatures. Training is not performed during refresh or page requests.

A second limited, interactive task, **MandiInsightsDailyPublication**, is registered and Ready for **00:05 IST**, next run **14 November 2026**. It runs `-B -m Code.intelligence.refresh --batch-only` from the same project directory. This closes the date-rollover gap: forecasts published at 22:30 expire at midnight, so the new task publishes the following day's estimates from already accepted history without another source request or model training. Its action/definition were validated before successful registration. The same missed-run, retry and overlap safeguards apply, including the shared publisher lock. Both tasks' inspected definitions and next-run times are recorded in the scheduler receipt. Neither first automatic invocation has happened yet.

### Running and checking the updated application

Final verification: the full safe backend run completed with **597 passed, 1 skipped and the same known frozen D-52 pre-run-lock assertion failure** in 325.33 seconds. The protected test expects an absent lock even though the authorized evaluation is already consumed; neither the test nor that lock was changed. After the final fixes and data publication, **111 focused backend tests passed** in 18.98 seconds, including four added checks for same-market storage rejection, coordinate fallback/ambiguity, study artifact integrity/availability gates and warehouse-cache invalidation. **41 frontend tests passed**, TypeScript compilation and the production build passed, and `git diff --check` found no whitespace defects. The existing large JavaScript bundle warning remains.

Native headless Playwright passed Strategies, Markets and Warehouses; twenty-crop exploration; edited quantities and multiple trips; alternative/scenario comparison; automatic 7/14/30-day storage options; applying a stored option with its four-step journey and correct forecast label; stale-option suppression after input changes; market and warehouse handoffs; maps; unavailable-crop handling; and mobile navigation/overflow. No page errors were reported. Screenshots and exact test outputs are in `Processed_Data/intelligence_v1/qa/`. The storage comparison was measured at **0.357 seconds** on the warm local API after caching deterministic warehouse simulations by date/configuration and removing repeated catalog reads. This is a local measurement, not a latency guarantee.

```powershell
Set-Location '<project-root>'
# Offline daily publication; no source requests or training
C:\Python313\python.exe -B -m Code.intelligence.refresh --batch-only
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Second PowerShell window
Set-Location '<project-root>\frontend'
npm run dev -- --host 127.0.0.1 --port 5173
```

```powershell
# Project root: manual incremental refresh, task inspection and local QA
powershell -NoProfile -ExecutionPolicy Bypass -File Code/intelligence/run_refresh.ps1 -Execute
Get-ScheduledTask -TaskName MandiInsightsDailyRefresh
Get-ScheduledTaskInfo -TaskName MandiInsightsDailyRefresh
Get-ScheduledTask -TaskName MandiInsightsDailyPublication
Get-ScheduledTaskInfo -TaskName MandiInsightsDailyPublication
C:\Python313\python.exe -B -m Code.intelligence.coverage
C:\Python313\python.exe -B Code/tests/browser_intelligence.py --base-url http://127.0.0.1:5173
```

Open `http://127.0.0.1:5173`. There is no need to reinstall the existing scheduled tasks. A deliberate future backfill should reuse its recorded scope and allowance, follow provider cooldowns and avoid resetting exhausted request ledgers. Existing independent studies and road caches are retained by their build commands; routine application startup requires neither retraining nor graph reconstruction.

## Dynamic discovery and two trading categories (13 November 2026)

This release replaces the historical twenty-crop selector on Strategies with options from the currently served, successfully published forecast batch. The default is **All eligible crops / Across India / 100 quintals / Medium truck / Both modes**. Historical-only crops such as Brinjal remain available in Markets and cannot become an active current-strategy selection. A stale crop, state or carried market is reconciled with an explanatory notice instead of silently persisting an invalid selection.

### Measured coverage and category leaders

- **325 discovered commodity names**, from the local source-file inventory and accepted source manifests. Filename-only discovery is explicitly unaudited; it does not imply reliable prices or forecasting eligibility.
- **56 audited historical crop datasets**, all reused without a crop-count or category quota. Previously the intelligence catalog published only twenty of these. The resulting operational registry has **115,722 market-variety series**, including unavailable historical series; this is not a count of current forecasts.
- **5 current forecast-ready crops and 5 strategy-ready crops**: Green Chilli, Onion, Potato, Tomato and Wheat. They retain **254 current forecasts** and **762 evaluated future-baseline quotes**. No new source observations were downloaded and no model was retrained during this change.
- **12 currently supported purchase-state options**, derived from mapped compatible forecast pairs rather than the routing-node inventory. The state options narrow when the crop changes.
- **898 intrastate scenarios** and **200 interstate scenarios**, totaling **1,098**. Both categories are ranked independently under the same economic and uncertainty policy. Changing shared inputs recomputes both rankings.

At the measured default quantity and truck, the intrastate leader is **Onion, Rawatsar APMC → Bhadara APMC, Rajasthan → Rajasthan**, variety **1st Sort**, grade FAQ. Forecast prices are **₹2,000 → ₹4,444/quintal**, freight **₹350**, estimated net margin **₹235,584**, adjusted comparison value **₹126,739.50**. The **10 km route is an approximate same-district-reference/access scenario**, not a measured distance between these mandi entrances. This substantial geographic limitation remains visible in the route evidence and comparison reserve; no road geometry is invented for it.

The interstate leader is **Onion, Shahzadpur APMC → Sahnewal APMC, Haryana → Punjab**, variety **Onion**, grade FAQ. Forecast prices are **₹2,000 → ₹4,800/quintal**, freight **₹4,260.31**, estimated net margin **₹266,739.69**, adjusted comparison value **₹141,339.69**. It uses the saved directed OSM reference route of **121.723 km**, including assumed endpoint access. Neither margin is a guaranteed realized profit. The exact live verification, category counts, identifiers, reserves and route basis are saved in `qa/dynamic-operational.json`.

### Discovery and admission

`Code/intelligence/discovery.py` combines existing audited ranking/archives, local source filenames and accepted commodity partitions. It removes the `head(20)`/minimum-crop-count publication restriction and distinguishes discovery from available historical data, current forecast support and mapped trading-pair support. It preserves exact commodity identity and existing aliases; it does not merge paddy with rice, whole with split commodities, varieties, grades or source eras. Existing source hashes, cleaning, units, retrieval timestamps and per-series eligibility remain enforced.

A newly accepted commodity can enter an operational release using its cleaned recent-source partition even without a legacy archive. Its persistence forecast still requires the existing 180-observation, 365-day span, reporting-density, freshness and availability checks. Tests cover both source-only release admission and a synthetic newly eligible commodity; a short series remains unavailable. Unknown storage classifications receive no assumed compatible facility. Future-price quotes remain unavailable for newly admitted crops until the separate horizon evaluation supports them; no historical error score or learned promotion is fabricated.

The established bounded collector is reused. Routine scheduled collection continues the commodities already represented in accepted partitions; it does not suddenly download all 325 discoveries. An explicit, bounded `--crop` backfill may target another discovered commodity. Request/byte ledgers, checkpoints, double-response validation and provider cooldowns continue to apply. Offline publication rebuilds discovery automatically after accepted data changes. Filename-only historical sources require auditing before their prices become operational.

### Classification, economics and alternatives

`Code/intelligence/states.py` maps recognized Indian state/UT names, explicit aliases and identifiers to stable project IDs. Intrastate means equal normalized state IDs; interstate means distinct recognized IDs. Districts are never substituted for states, and unknown/missing states cannot manufacture an intrastate pair. Candidate generation groups exact crop, variety, grade and source before pairing, preserving the economic calculations, capacity-constrained trips, losses and storage rules.

Each category ranks all compatible mapped candidates independently using net margin after historical error, recent observed movement, report age and route-evidence screening. The existing practical-tie policy remains. Missing historical error uses a centralized conservative comparison assumption, not a confidence percentage. The category leader explains the next ranked option using actual economic and uncertainty differences. Cross-crop alternatives are labeled explicitly and compared at the same requested quantity; same-product comparisons remain available in the detailed journey.

Each category returns up to twelve ranked rows. An explicitly selected eligible scenario is also retained if it moves below that visible shortlist on refresh; an ineligible selection is cleared. Selecting an alternative changes the active detail view and displays **Selected alternative**, without replacing the system leader's label. Category mode switching preserves crop/state inputs and cross-category comparisons. Empty categories keep their own explanation while the supported category remains visible.

The main quantity/truck controls and expandable **Comparison assumptions for both modes** support shared freight rate, truck capacity, handling charges and handling loss. They rerank both categories consistently. Blank overrides use configured truck/crop defaults. The separate detailed editor remains a selected-trade simulation, clearly labeled rather than presented as a reranked global recommendation. Actual row assumptions initialize that editor so custom freight, capacity and handling values do not silently revert. Direct-versus-storage comparison, crop suitability, simulated free capacity and separate predicted/simulated price modes remain functional.

### APIs and publication integrity

- `GET /api/v4/strategies`: independent `groups.intrastate` / `groups.interstate`, each with `best`, ranked `rows`, `candidate_count` and an empty reason; dynamic crop/state filters; effective reconciled selections and notices; current forecast/strategy-ready crop lists; date, `dataset_version` and `batch_id`. Existing crop/state/quantity/vehicle/market filters remain; `mode`, `selected_id`, `handling`, `loss`, `rs_km` and `capacity_q` extend exploration.
- `GET /api/v4/discovery`: discovered/historical/forecast-ready/strategy-ready counts, current crop lists and per-commodity status flags, bound to the same dataset/batch identifiers.
- `GET /api/v4/overview`: explicit dataset and batch identifiers alongside existing configuration and freshness. Coverage and catalog reads follow the served release.

`daily_v1/serving.json` is one atomic pointer to a completed price release/batch and immutable copies of its coverage, quality and precomputed-strategy views. The refresh process uses a local build context while preparing the next publication; other API requests continue reading the last committed snapshot. Catalog reads come from the release manifest rather than a mutable discovery draft. Failed publication restores prior pointers and derived views, including the serving pointer; tests inject a failure after new coverage is written and verify that the old catalog/price/filter view survives. A request spanning a batch switch is rejected for retry rather than returning mixed versions. Existing publisher locks, dead-process recovery, source cooldown and both Windows schedules remain unchanged.

### Frontend and verification

The Strategies page now puts two compact category leader cards above the selected decision journey. Both show crop/variety/grade, buying and selling states/markets, predicted prices, travel/freight, net margin, route/data-quality evidence and a calculation-derived next-alternative explanation. Expandable alternative rows show crop and market choices, freight/margin differences, distance and adjusted value. Shared controls, cross-mode comparison and selected-alternative labels preserve context. Buying-market links open the corresponding crop, state, district and series; storage links retain crop compatibility. Markets and Warehouses keep the existing beige/white/forest-green layout and historical exploration.

Verification completed: **614 passed, 1 skipped and the same documented frozen D-52 test failure** in the full safe backend run (237.94 seconds). Later focused verification, including shared-cost controls, source-only admission, retention of a selected pair below the visible shortlist and injected publication failure, completed with **128 passed** (15.42 seconds). **46 frontend tests passed**, TypeScript compilation and production build passed; the existing bundle-size warning remains. Native headless Playwright passed both category leaders, dynamic eligible-only filtering, shared quantity/capacity/freight recalculation, opportunity-to-specific-market handoff, mode switching, alternative labels, cross-category comparisons, storage forecasts/simulations, market/warehouse handoffs, stale Brinjal URL recovery, maps and mobile overflow/navigation, with **no page errors**. An additional offline refresh reported **unchanged** and retained the same dataset/batch identifiers and forecast/scenario counts. Screenshots and logs are in `Processed_Data/intelligence_v1/qa/`.

Remaining limits: the 325-name inventory is local-source discovery, not an exhaustive live nationwide commodity directory. Most discovered crops still lack audited/recent eligible market histories. Many locations remain district/locality references and unsupported roads are explicitly approximate. Warehouse operating figures remain deterministic simulations where unverified. The current crop/forecast counts can expand automatically as accepted history meets the unchanged rules; discovery alone does not make a forecast or trade. No frozen research artifacts or consumed evaluations were modified or rerun, and no code was staged, committed or pushed. Run commands and the registered daily schedules remain as documented above.

## Single-mode Strategies and automatic development evaluation (13 November 2026)

This section supersedes the preceding side-by-side category presentation. The Strategies page now has a prominent **Intrastate / Interstate** segmented selector, one system recommendation, three inline competitors, one inspected route/cost view, storage comparisons and expandable assumptions. The default mode is selected by ranking the category leaders under the current crop, purchase region, quantity, vehicle and cost policy. It is not a fixed crop, market or mode. At the measured all-crop defaults, **Interstate / Green Chilli** ranks first after the newly accepted location references are applied.

### Mode and competitor behavior

The selected mode controls the recommendation, crop/state options, competitors, selected markets, explanation, map, economics and storage comparison. Switching modes preserves shared inputs. If a selected crop/region cannot support the mode, the crop remains selected with an unavailable label and a practical explanation; the user explicitly chooses to widen the region, inspect market forecasts, show all eligible crops or try an eligible alternative. No unsupported crop is silently substituted.

The recommendation contains current buying/selling prices, states, quantity, freight, modeled net margin, a connected journey and three calculation-derived insights. The next-best competitor explanation uses actual economic differences. Three ranked alternative rows show crop/variety/grade, buying/selling states and markets, distance, freight, margin, adjusted ranking value and the margin difference from the recommendation. Cross-crop rows explicitly state that quantity/truck/comparison policy are shared while configured crop losses can differ. Margin bars represent modeled net margin; uncertainty-adjusted ranking value is separately labeled.

Inspecting a competitor changes its compact route/economics view without relabeling or replacing the system recommendation. Custom edits and storage choices affect the inspected trade; their default-policy competitor insight is hidden rather than applied to different assumptions. Returning to the recommendation reinitializes its editor and economics, including when a custom stored scenario uses the same market-pair ID. This removes the former duplicate large recommendation/detail headings. Markets, Warehouses, their handoffs and the beige/white/forest-green styling are retained.

### Per-crop availability and investigation

Current eligible forecast counts are unchanged. Mapped compatible scenarios now number **1,198 total: 960 intrastate and 238 interstate**:

- **Green Chilli:** 15 forecasts; **14 intrastate / 24 interstate** pairs.
- **Onion:** 61 forecasts; **52 intrastate / 66 interstate** pairs.
- **Potato:** 74 forecasts; **148 intrastate / 108 interstate** pairs.
- **Tomato:** 31 forecasts; **14 intrastate / 40 interstate** pairs.
- **Wheat:** 73 forecasts; **732 intrastate / 0 interstate** pairs.

The audit separates raw compatible pairs from state normalization, geographic acceptance and candidate enumeration. It records forecasts by state, mapped forecasts, exact variety/grade/source groups, unknown states and mode-specific reasons in `phase5/mode_availability.json`; `/api/v4/mode-availability` exposes the same analysis bound to the forecast batch.

**Wheat's missing interstate support is genuine under current data.** Its 73 forecasts span Madhya Pradesh (60), Uttar Pradesh (10) and West Bengal (3), but their exact variety/grade/source groups do not overlap across states: UP reports Dara, while the WB/MP groups differ. There are **zero compatible interstate pairs even before geographic filtering**. Only 33 Wheat forecasts currently have accepted geographic references, all in MP; that is an additional coverage limitation, not the fundamental cause of the absent interstate category. No variety/grade/source rule was weakened, and no artificial interstate trade was created.

**Green Chilli's absent intrastate category was a geographic coverage gap.** There were 46 compatible intrastate and 40 interstate pairs before location filtering, but the original accepted references left only 0 / 8 pairs. A bounded lookup added five unique exact country/state/town matches for **Lalbagh, Warangal, Kalna, Habra and Narnaul**. The six-look-up build accepted five and rejected one; two preliminary diagnostic lookups were also made. Composite names and ambiguous matches remain unresolved. Matching follows the existing exact country/state/name and geographic-dispersion checks; the endpoint's result fields and GeoNames provenance are documented by [Open-Meteo](https://open-meteo.com/en/docs/geocoding-api).

The new points are **market-town references, not verified mandi entrances**, saved separately in `phase5/locality_references.json`. They are selected by exact market identity and do not replace the district reference for other markets in the district. Unsupported road journeys retain the existing approximate distance/time/freight method without fabricated geometry. Green Chilli now has 11 mapped forecasts and 14 / 24 valid pairs; shared market references also improve Potato and Tomato coverage. No price observations were downloaded or invented, and all current forecasting thresholds remain unchanged.

### Dynamic training and new crop admission

The previous independently versioned studies remain intact: Ridge and HistGradientBoosting price candidates for the original twenty-crop intelligence cohort, the twenty-crop 7/14/30-day study (sixty horizon cohorts), and the separately evaluated agricultural-factor comparisons. Persistence remains the operational model.

`Code/intelligence/learning.py` adds a separately versioned **dynamic-development-v1** workflow under `phase5/learning_v1`:

1. A successful refresh queues newly forecast-ready crops or changed evaluation-source identities. Existing unchanged twenty-crop artifacts are recognized by validated hashes/source identity. Filename-only discoveries do not trigger indiscriminate training.
2. The refresh CLI may dispatch **one bounded offline worker job** after publication. Training is outside API requests and the refresh's price-generation transaction. The worker has its own lock, immutable requests/receipts, dataset/source identifiers and content-addressed model runs. Existing Windows tasks invoke the same CLI; no additional persistent task or unrelated service was installed.
3. Audited archives and source-only commodities use the same path. Source-only jobs fingerprint only the permitted development slice, so changing recent/target-day observations does not trigger repeated fitting. A changed development slice or source identity can enqueue a new job. Unchanged allowed history reuses its completed evaluation.
4. Development data is restricted to **2018-12-31 or earlier**, with training labels through **2016-12-28**, 2017 selection, 2018 confirmation, an explicitly assumed **three-day reporting delay**, and at most twelve training-selected market series. Current-day and future features do not use their target observation. Protected 2019+ and consumed evaluation windows are not scored. These are revised-archive simulations with unknown original publication vintages, not measured live forecast accuracy.
5. Persistence, seasonal naive, moving average, Ridge and HistGradientBoosting are evaluated for current-day, 7-, 14- and 30-day targets where coverage supports both validation years. Metrics, year/market/freshness breakdowns, supported series, dataset/source versions, fitted candidate artifacts and their checksums are retained. No calendar targets or error estimates are fabricated for insufficient history.
6. Learned promotion requires at least 5% MAE improvement in **each** validation year, at least 100 observations/year, positive finite predictions, and independently verified current-regime availability evidence. Successfully fitting a candidate never deploys it. No new candidate earned promotion.

Two bounded real-data jobs verified the path outside the earlier twenty-crop model cohort: **Mustard** and **Bengal Gram(Gram)(Whole)**. Both evaluated all four horizons and five methods, producing **40 aggregate score rows and eight artifact files containing sixteen fitted learned candidates**. Historical persistence MAE in INR/quintal was:

- Mustard: **61.80 current-day / 90.40 seven-day / 116.82 fourteen-day / 141.49 thirty-day**; matched validation rows 497 / 402 / 397 / 359.
- Bengal Gram: **150.67 / 200.55 / 250.01 / 313.96**; rows 406 / 331 / 318 / 297.

For current-day Mustard, Ridge MAE was 61.28 (0.84% aggregate improvement), insufficient under the two-year and prospective gates; HGB was worse at 72.52. Bengal Gram Ridge/HGB were worse than persistence at 176.57 / 168.96. All artifacts retain `serving_approved=false` and persistence as the serving choice. These two crops currently lack eligible recent forecasts; completing development evaluation did not bypass freshness or admit them into trading filters.

New commodities without adequate permitted development history keep their observations and may receive an operational persistence quote only if the unchanged market-series rules pass. Missing historical error remains missing; rankings use at least the configured conservative exposure reserve plus measured-movement screening, with an explicit unavailable-error label. Dynamic current-day error evidence and future-horizon support are exposed only after source and metric/artifact integrity checks. Future predictions remain unavailable without an evaluated horizon and a current eligible parent quote. A subsequent offline publication queued **zero new jobs** for the unchanged five current crops and preserved **254 current forecasts / 762 future quotes**.

### Verification and operation

Full safe backend run: **629 passed, 1 skipped, 1 unchanged frozen D-52 pre-run-lock assertion failure**, in 254.76 seconds. The final focused run completed with **142 passed** in 21.95 seconds, covering automatic mode choice, mode-specific choices, preserved unsupported crops/regions, competitor arithmetic, approximate-route admission, geography diagnostics, outside-twenty admission, real synthetic candidate fitting, source fingerprinting, publication rollback, promotion gates, model integrity, dynamic future support, conservative unvalidated-error screening and serving without training. **46 frontend tests passed**, along with TypeScript compilation, production build and real headless desktop/mobile checks; the existing bundle-size warning remains. The browser checks include storage-to-direct reset for the same pair, crop-preserving Wheat recovery, recovered Green Chilli intrastate trading, input preservation, market/warehouse navigation and overflow. No page errors were reported. Exact logs and screenshots are retained in `Processed_Data/intelligence_v1/qa/`.

Both existing limited interactive Windows tasks remain **Ready**: 22:30 source refresh and 00:05 offline publication, while the user is logged in. Provider cooldowns, request budgets, atomic serving publication and rollback are preserved. No credentials, accepted raw prices, frozen research artifacts or Git history were changed; nothing was staged, committed or pushed.

```powershell
# First PowerShell window
Set-Location '<project-root>'
C:\Python313\python.exe -B -m Code.intelligence.refresh --batch-only
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Second PowerShell window
Set-Location '<project-root>\frontend'
npm run dev -- --host 127.0.0.1 --port 5173
```

```powershell
# Optional controlled offline model-maintenance worker, from the project root
C:\Python313\python.exe -B -m Code.intelligence.learning enqueue
C:\Python313\python.exe -B -m Code.intelligence.learning work --max-jobs 1
```

Open `http://127.0.0.1:5173`. Remaining limitations are incomplete recent crop coverage, unresolved market geographies, approximate travel where directed paths are unavailable, simulated warehouse operations, and retrospective development evidence that does not establish current-regime learned-model superiority.

## Latest Markets intelligence revamp — 13 November 2026

The Markets-only implementation and its eleven-part completion report are recorded in [Markets_Intelligence.md](Markets_Intelligence.md). It includes the compact workspace, environmental/geographic sources, route and storage integration, transparent decision contributions, API contracts, current verification results and exact launch commands. Earlier research and publication safeguards remain in place.
