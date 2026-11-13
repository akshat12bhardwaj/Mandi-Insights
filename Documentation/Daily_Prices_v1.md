# Independent daily price extension — v1

Implemented 2026-11-11 as an additive extension of the existing application. The original weekly models, historical analytics, arrivals, weather, production, warehouses, routing, all existing endpoints, and the owner's uncommitted frontend redesign are retained. Nothing has been staged, committed or pushed. No notebook, frozen source file, run lock, protected evaluation output, or prior research decision was changed or rerun.

## Availability study and selection

The existing source inventory contains 325 commodity CSVs, totaling 4,745,859,660 bytes. All filenames and sizes are recorded in `Processed_Data/daily_v1/inventory.csv`. A full price-quality and series-continuity audit covers 56 plausible high-volume and category-diverse crops (not every one of the 325 commodities). Candidate coverage includes vegetables absent from the earlier APY-driven 40-crop audit, whole pulses, cereals, oilseeds, fruit and cash crops. No new external dataset was downloaded.

`Processed_Data/daily_v1/crop_ranking.csv` contains every audited candidate, rank and selection result, raw/usable counts, date bounds, reporting years, state/district/market/variety counts, weekly cells, established >=365-date reference counts, daily eligible series, missing-calendar frequency, reporting gaps, duplicate/conflicting/anomalous counts and current freshness. Each crop's local `archive/<id>/series.parquet` provides these measures at state-district-market-variety grain. Counts are observations, not imputed calendar days. A missing-calendar day includes holidays and non-reporting; it is not necessarily a source defect.

Ranking sorts daily eligible series at the crop's own source end, then established >=365-date series, then usable rows. A minimum of ten eligible series is required for category allocation. Onion, Potato and Wheat remain. Category minima are cereals 3, pulses 2, vegetables 3, fruit 2, oilseeds 2, cash crops 1; remaining slots follow continuity rank. This is a historical support ranking, not a national-volume ranking or fresh-data ranking. The catalog records 20 selected crops. Exact measured counts are in the ranking CSV and catalog; no metrics are invented.

Selected crops:

- Cereals and grains: Wheat, Rice, Paddy(Dhan)(Common).
- Pulses and legumes: Bengal Gram(Gram)(Whole), Arhar (Tur-Red Gram)(Whole).
- Vegetables: Onion, Potato, Tomato, Green Chilli, Brinjal, Cauliflower, Cabbage, Cucumbar(Kheera), Pumpkin, Carrot.
- Fruits: Banana, Apple.
- Oilseeds: Mustard, Soyabean.
- Commercial or cash crops: Cotton.

The selected archive contains 29,780,180 raw records and 29,379,491 usable observations spanning 24 reporting years (2001–2024). The archive ends 2024-02-01 for Wheat, Soyabean and Tomato; the other selected crops end 2024-02-02. Original minimum dates and distinct-year counts differ by crop and are in the CSV. Before the November 12 refresh, only Onion, Potato and Wheat had recent data.gov.in observations, ending 2026-10-25. That initial registry contained 70,311 source-market-variety-grade series and issued zero eligible predictions on November 11. See the dated follow-up below for the partial refresh and current predictions. Historical support alone does not satisfy the goal of current, operational estimates for all 20 crops.

## Dataset and time contract

The extension lives in `Code/daily/` and `Processed_Data/daily_v1/`; it never writes established Phase 8/9 or candidate datasets. Dataset versions contain a content-derived release suffix; model version is `daily-persistence-v1`. Release manifests bind observation, registry and model checksums. Changes to a held archive source refuse an in-place rebuild and require a new version. Releases retain their own model and registry, and batch pointers publish atomically.

Price cleaning reuses the project's duplicate-structure and trailing-reference helpers and the existing price rules: identical copies collapse; conflicts are excluded; non-positive/non-finite prices become unavailable; min/max inconsistency and modal-outside-range are excluded; >=50x scale errors are excluded, >=10x review records retained. Arrivals are neither inferred nor used. Invalid geographic/date keys and ambiguous daily keys are excluded. Observation files preserve the original source path/hash (manifest), zero-based source row or raw record reference, source identity, observed price, reporting date, grade, and recorded availability timestamp.

Archive units are explicitly Rs/quintal in column headers; data.gov.in prices use the existing project's documented INR/quintal contract. No silent unit conversions, fuzzy market joins, grade pooling, or variety merges occur. Rice and paddy, whole and split pulses, and different varieties stay separate. Naming normalization is limited to whitespace/NFKC and explicit commodity aliases. Geographic spelling variants remain source-specific; the extension does not claim that Keralam/Kerala or renamed districts establish market identity. Historical archive and data.gov.in series are intentionally separate, even at matching display names. The original three crops retain the established FAQ-only policy. For the new crops, preprocessing version `daily-recent-v2-explicit-grades` retains each reported grade as a separate identity, including fruit grades A/B/Local; a cereal-oriented FAQ filter would incorrectly discard them. All new raw increments receive the extension's R01–R09 rules and conflict exclusion. The processing version enters the source fingerprint and release manifest, so prior source snapshots and releases remain intact.

Operational issue timestamps are timezone-aware, and today's date is determined in IST (fixed UTC+05:30, portable on Windows). Features use only observations with reporting date strictly before the target AND actual availability timestamp at or before issue. Today's observation is displayed separately and cannot enter today's forecast. Retrieving an old record today does not make it available in a historical backtest. Archive availability is the extension's first ingestion timestamp; its original publication vintage is unknown. Candidate records retain actual retrieval timestamps.

Initial daily eligibility, fixed before the availability audit: >=180 distinct past observations, >=365 days of history span, >=60 observations in the previous 365 days AND reporting density >=25% in that year (therefore the density threshold usually binds at 92 dates). Age <=3 days is fresh enough for `prediction_available`; 4–7 days is `stale_prediction`; >7 days is withheld as `stale_unavailable` if enough lifetime history exists. Otherwise status is `insufficient_history`. The historical >=365-observation reference is reported separately and is unchanged. These conservative daily defaults test continuity and recent reporting; the seven-day cap is a provisional operational guard, not a statistically proven universal optimum.

## Development study and model artifacts

`development/protocol.json` was saved before scoring. This is a separately versioned **development simulation**, not a rerun of any frozen experiment or a new untouched test. Only archived targets through 2018-12-31 are loaded for scoring: training targets 2010–2016, development targets 2017–2018. The old research evaluation windows (2019 onward) are not scored or used for model selection by this extension. Operational use of observed current prices is not a scoring of the research holdout.

Up to twelve series per crop are selected exclusively using pre-2017 history: >=365 dates, most observations, round-robin states. Wednesday issue dates provide comparable coverage across five models. Three-day reporting delay is assumed because publication vintages are absent; no-report target dates are counted and never filled. Persistence, exact seven-calendar-day seasonal naive (persistence fallback on unreported days), last-seven-observation mean, standardized Ridge(alpha=10), and HistGradientBoosting(max_iter=100, max_leaf_nodes=7, min_samples_leaf=30, l2=10, random_state=711) share identical evaluation dates. Learned models predict changes relative to the last price. Features are past price ratios, means, volatility, momentum, days since report and cyclic calendar terms. No weather, APY, arrivals, or unverified market mapping enters the models.

Measured MAE, RMSE, sMAPE, relative improvement and coverage are in `development/by_crop.csv`, `by_market.csv`, `by_observation_age.csv` and `coverage.csv`; errors are saved locally in parquet. These are conditional on an observed target and eligible history, not all calendar-day accuracy. All five methods use the same target rows. Non-positive regression outputs are counted and scored without dropping or clipping them; Ridge produced one such output and is not operationally accepted. HGB and Ridge each improved pooled crop MAE for 5 of 20 crops, while moving average improved 3; this is descriptive development evidence, not proof of robust market-level or prospective superiority. No bootstrap significance or fresh prospective evaluation has been completed.

Persistence is the only operational model artifact. It requires no fitted coefficients: the approved recipe and exact dataset version are loaded from `model.json`; no training happens in API requests. Ridge/HGB are fitted and evaluated offline only; no deployable learned artifact is promoted. The UI shows crop-level historical simulation MAE with its period and scope, and returns no calibrated uncertainty interval. Learned models, reporting-delay assumptions and the age cap require fresh prospective validation before stronger reliability claims.

## Batch inference and API

`python -B -m Code.daily batch` loads the release artifact and verifies source hashes. Given the same dataset, model and timezone-aware `--issue` cutoff it produces the same predictions. All series are computed once per batch. Forecasts are stored in an indexed SQLite file, read only by API workers; no separate database service is required. The API caches release metadata, reads one forecast by series ID, and lazily reads filtered parquet history. If the target date changes before another batch is generated, prices are suppressed as `batch_expired`. A release/batch/model version mismatch or corrupt artifact returns 503. An operational cutoff before the dataset/model release timestamp is rejected; an artifact built later cannot be backdated into an earlier forecast. No automatic scheduler is installed.

New endpoints, all under `/api/v3/daily`:

- `GET /crops`, `/categories`, `/metadata`, `/freshness`.
- `GET /locations?crop=Onion[&state=Maharashtra]`.
- `GET /markets?crop=Onion&state=Maharashtra&district=Nashik`.
- `GET /today?series_id=<returned ID>`.
- `GET /history?series_id=<returned ID>&limit=90` (1–365 observed points).

Unsupported crop/location/series returns 404; invalid limits return 422; missing artifacts return 503. Prediction responses validate positive-or-null prices, source, versions, issue date, target date, last known observation, status, provenance, today's independent actual, and historical error information. The existing `/api/capabilities` research price entry continues to describe the original weekly research capability; daily operational status is reported by `/api/v3/daily/metadata` and `/freshness`.

Browser checks verified the compact desktop layout, mobile layout, cascading location/market selection, stale-state wording and observed-history chart. The React `/today` screen adds category, crop, state, district, market and variety/source selection, forecast/actual separation, last observation/date, staleness status, version/issue context, and optional lazy-loaded history. Missing days are chart gaps. Source identities are visible rather than blended. All original routes remain.

## Refresh attempt — approved, stopped by provider failure

`Code.daily.refresh` defaults to printing a plan without networking. It uses the existing secure credential loader, double-fetch completeness and equality checks, strict crop/date validation, request and streaming byte budgets, accepted partition hashes, immutable raw snapshots, and incremental resume. It stops on truncation, changed responses, rate limits, invalid partitions or exhausted budgets. No automatic retry/paging or enormous download occurs. Empty reports are retained as missing observations, never zero prices. Existing accepted days are skipped; revisions to held days need a future versioned refresh policy.

The prepared full-coverage proposal is 2025-11-08 through 2026-11-08 inclusive for the selected 20 crops: 7,320 crop-days, at most 14,640 requests, with an explicit byte cap. This may require several sessions and API quota; actual available coverage is unverified. The provider must recognize the commodity labels, and a complete response must be below 5,000 rows. No empirical current coverage is claimed until collection and rebuild succeed. The owner approved the capped refresh on 2026-11-11. The attempted run stopped with a provider/network or invalid-JSON response failure before any crop-day was verified and saved. No new observations were accepted; the existing release and batch were retained. The original collector did not persist exact failed-request traffic or the exception subtype, so these amounts remain unknown rather than invented. See `Processed_Data/daily_v1/refresh_attempt.json`. No subsequent network requests were made. The collector now persists request/byte usage across runs and records sanitized failure classifications. The original approval scope is blocked from automatic resume because its exact remaining allowance cannot be established.

Print the plan (no network):

```powershell
Set-Location '<project-root>'
C:\Python313\python.exe -B -m Code.daily.refresh --start 2025-11-08 --end 2026-11-08
```

For reference, the approved command was the following. It must not be repeated under the original allowance while its failed-run accounting remains unresolved. Release and batch are only appropriate after successful collection or reviewed partial coverage:

```powershell
C:\Python313\python.exe -B -m Code.daily.refresh --start 2025-11-08 --end 2026-11-08 --budget 14640 --max-mb 1000 --execute
C:\Python313\python.exe -B -m Code.daily release
C:\Python313\python.exe -B -m Code.daily batch
```

Release and batch must be run only after collection's success or after reviewing any partial coverage. Fresh observations become available at actual retrieval time; rebuilding with a historical issue time cannot backdate them.

## Running and verification

From the project root, existing installed dependencies suffice; SQLite and fixed-offset IST need no added packages.

```powershell
# First build from existing local raw data (does not download, train, or score).
C:\Python313\python.exe -B -m Code.daily build
# Optional, development simulation only; never invoke frozen evaluation runners.
C:\Python313\python.exe -B -m Code.daily evaluate-development
# Generate a later batch after any source change/release, or on the next IST date.
C:\Python313\python.exe -B -m Code.daily batch
# Window 1
C:\Python313\python.exe -m uvicorn Code.api.main:app --host 127.0.0.1 --port 8000
# Window 2
Set-Location '<project-root>\frontend'
npm run dev
```

Open `http://127.0.0.1:5173/today`. If an older API is already running, restart that process to load the extension. Do not terminate an unrelated process occupying a port. Vite may select 5174 if 5173 is occupied.

Verification on 2026-11-11: 95 safe backend tests passed, covering the daily pipeline/refresh, existing API/v2/logistics, existing app, weather and routing. All 27 frontend tests passed; TypeScript and Vite production build passed. The build reports a >500-kB main bundle warning (the new daily chart is separately lazy loaded). Full repository tests and protected one-time evaluations were not run. The existing known frozen pre-run assertion failure is left unchanged. Synthetic tests cover availability-cutoff leakage, today's actual exclusion, IST midnight, sparse/stale histories, aliases, baselines, learned fitting/inference, vectorized simulation parity, incremental resume, tamper detection, API contracts and unsupported locations.

Real-data API smoke check: 20 crops, 70,311 indexed series, zero eligible current predictions, observed history available; initial catalog load about 0.224 seconds and a warm single-series lookup about 0.004 seconds in a local TestClient run (observational timings, not benchmarks). Remaining work is approved fresh-data acquisition, coverage verification, prospective reliability/staleness validation, and optional reviewed market-identity bridging; it is not a completed live 20-crop price service yet.

Refresh follow-up checks: 24 daily/refresh tests passed after adding durable budget accounting and sanitized diagnostics, including validation-failure accounting and refusal to reset a consumed budget on resume. No fresh source coverage or current predictions were fabricated.

## November 12, 2026 follow-up: partial refresh and operational predictions

The owner explicitly approved a new allowance of 14,640 requests and 1,000,000,000 response bytes in this chat. The new scope is November 11, 2025 through November 11, 2026 inclusive, for the same 20 selected crops. The incomplete November 11 allowance was not reset or reused. Requests now process the newest dates first. An initial request timed out; a controlled retry using the curl user-agent used by the existing provider integration received data, then also stopped on a provider timeout. There is no automatic retry loop.

Durable accounting records **75 requests and 8,460,472 received bytes**, including failed attempts. **36 verified crop-day partitions containing 9,971 raw records** were accepted; three were explicit empty reports. Coverage is November 10–11, with at least one verified partition for each of the 20 crops. This is a partial acquisition, not the proposed full year. See `refresh_attempt_2026-11-12.json` and the local usage ledger `refresh_usage/ee95b79321d0caa70a10.json`. The command below resumes that same allowance and skips verified partitions; it does not grant a new allowance:

```powershell
C:\Python313\python.exe -B -m Code.daily.refresh --start 2025-11-11 --end 2026-11-11 --budget 14640 --max-mb 1000 --execute
```

The refreshed release is **`daily-prices-v1:f09d6d1b1a7790c9`**, with model `daily-persistence-v1` and **75,396** source-market-variety-grade series. A batch issued at **2026-11-12 14:10:50 IST** contains **208 eligible predictions**: Onion 61, Potato 74 and Wheat 73. There are 49,329 insufficient-history series and 25,859 stale-unavailable series. Each count is at the complete series grain, not just a market-name count. Eighteen crops have usable observations through November 11. Paddy(Common) and Arhar(Whole) returned explicit empty reports and retain their February 2, 2024 archive end. Every other newly added crop has too little recent history to meet the daily eligibility policy. Thus **the live 20-crop forecasting objective remains incomplete**.

The FAQ-only rule inherited from the original three-crop pipeline discarded all received Banana and Apple observations because their reported grades were A/B/Local/etc. Preprocessing version `daily-recent-v2-explicit-grades` corrects this for the new crops, with grade-specific identities and unchanged legacy FAQ filtering. The transformation version enters snapshot fingerprints and source manifests; hashes of all observations referenced by both prior releases were verified unchanged. No archive/feed identity bridge was introduced to manufacture historical continuity.

Batch inference now parses source dates and availability timestamps once, filters by issue cutoff, and groups actual observations to apply the same shared eligibility policy. Tests compare complete grouped payloads with scalar forecasts across sparse, stale, future-retrieved, same-day and unavailable histories. The final real-data batch took **24.66 seconds** on this machine (an observed run, not a benchmark). No data collection, training or evaluation occurs inside an API request. Missing history files return 503; malformed provider metadata cannot masquerade as an empty report.

Verification after the changes: **107 safe backend tests passed**, **27 frontend tests passed**, and the TypeScript/Vite production build passed. Real-data API checks passed for catalog/freshness and prediction/history retrieval for each of the three currently eligible crops, plus unsupported-series rejection. Earlier real-data grouped/scalar checks matched exactly. Saved development protocol/result checksums matched; the development study and all protected evaluations were not rerun. The build still warns about its >500-kB main bundle; backend tests report a Starlette/httpx deprecation warning and release generation reports a pandas future warning. No test failed. No files were staged, committed or pushed, and the existing uncommitted redesign was preserved.

The 56-candidate historical ranking, raw/usable counts, reporting coverage, continuity and eligibility evidence remain in `crop_ranking.csv`; the 20-crop per-model MAE/RMSE/sMAPE, per-market and observation-age results remain in `development/`. They describe the 2017–2018 reporting-delay development simulation, not measured live accuracy. Prospective error calibration and validation of the provisional seven-day staleness cap remain outstanding. Reliable current forecasts for the other 17 crops require more verified recent history; the provider interruptions prevented collecting that history in this run.

## Decision-support workflow — November 12, 2026

The existing Today page now prioritizes today's estimate, a concise freshness indicator, district weather context, an observed/predicted trend and a buying summary. The existing visual theme, sidebar and all other pages remain. Tabs expose buying comparisons, storage candidates, transport scenarios and methodology. Provenance, last observations, historical errors, model versions and issuance metadata remain available in Details and the existing API. Selection defaults to an eligible forecast with a known district road reference when possible; unsupported historical selections remain explicitly unavailable and offer eligible alternatives.

`Code/decision/` is an independent, deterministic cost-comparison service. New typed APIs in the existing FastAPI application are `GET /api/v3/decisions/options?crop=...`, `POST /api/v3/decisions/compare`, and `GET /api/v3/decisions/weather?series_id=...`. The comparison response includes market costs, both existing precomputed road-route objectives, storage candidates and a bounded decision summary. No model is trained, source data collected, artifact rewritten or optimization solver invoked in comparison requests.

Only eligible current predictions enter comparisons; expired or future-issued batches are withheld. Prices are compared directly only within the same crop, variety, grade and source. Up to five rows are displayed from the chosen state (or all states); if the state has no eligible estimates, the response explicitly expands to available states. Different-grade alternatives can be selected but are not ranked as equivalent purchases. There are currently 208 forecast series and exact verified district-reference matches for 49: Onion 10, Potato 15 and Wheat 24. Market-site coordinates remain unverified.

Costs use quintals, with ten quintals per tonne. Procurement = predicted INR/quintal × quantity. One-trip transport uses either an inclusive user-entered INR/tonne-km freight rate or user-entered fuel price and vehicle efficiency, plus fixed trip charges; freight and fuel are never added together. Handling is entered separately. A landed scenario requires a destination reference, a complete rate assumption, and separately entered market and destination access-road distances. Precomputed district-road distance is not relabelled as a market-address route, and straight-line snap gaps are never charged as road kilometres. The lowest-cost label is conditional on the fully costed comparable subset and requires at least two such series. One complete scenario can be priced but cannot establish the best buying option. All estimates exclude unmodeled vehicle-capacity constraints, taxes, return travel, waiting, spoilage, shrinkage and financing.

Storage candidates use existing OSM-reported facilities and node-to-warehouse road links. Reported/derived facility labels do not establish crop suitability. Capacity, availability and operator tariffs remain unknown. A user-entered storage rate yields quantity tonnes × days / 30 × INR/tonne-month, clearly labelled as an assumption. An optional market→facility scenario includes its separately entered access roads; it is an alternative to delivery, not an added warehouse leg after delivery. Future revenue and potential net margin remain null because there is no validated future selling-price artifact. No storage-for-profit recommendation is made. Users must confirm crop-specific storage conditions, especially cold-storage or ventilation requirements, with the operator.

Weather review: the existing collection manifest has 36 source rows; 34 have no retrieval timestamp, and the other two were retrieved in September 2026. None provides original publication-availability timestamps for a 2017–2018 daily weather comparison. `Code/decision/weather.py` therefore rejects missing/future availability and requires seven complete previously available daily observations for rainfall, temperature and humidity features. Price-only, price/calendar, price/weather and price/weather/arrivals input variants are prepared separately, but no new real weather or arrivals comparison is scored or promoted without those prerequisites. The closed weekly weather study in `Data_Source_Review.md` §8.11 failed its acceptance rule for all three legacy crops; it was read as evidence, not rerun or used to claim daily performance. Current Open-Meteo context is fetched only for exact verified district references and is explicitly excluded from the issued price forecast, including when retrieved after issuance.

Verification: 120 safe backend tests and 30 frontend tests passed; TypeScript/Vite production build passed. Tests cover price/grade eligibility, expired/future batches, weather cutoffs, units, missing destinations and rates, route costs, unknown warehouse suitability/capacity/tariffs, unavailable forecasts, input validation, profit withholding, applied-versus-draft controls, Details, crop switching and keyboard tabs. Real-data comparisons passed for Onion, Potato and Wheat using test-only transport assumptions. Browser checks exercised a real delivery scenario, both OSM objectives and route geometry, storage candidates, and desktop/390px mobile layouts; mobile content did not overflow horizontally. Protected evaluations were not rerun; the known main-bundle size and Starlette/httpx warnings remain.


## Trading v2 and daily updates — November 12, 2026

The existing Today experience now has three primary tabs: Today's Decision, Route Analysis and Storage Analysis. Crop/market selection, quantity, objective, preferred destination/selling market, maximum road distance, storage duration and all assumptions share one state. Valid input changes are debounced; all tabs use the same cached comparison response. The calculated plan precedes the price chart; methodology remains optional. Forecasts and scenarios refresh at one-minute intervals while active, and a dataset-version change refreshes the historical chart. Previous-run forecasts are explicitly distinguished from current estimates when a batch expires.

`POST /api/v3/decisions/trading` returns the typed `trading-scenarios-v2` contract, preserving the original `/compare` endpoint. It includes compatible buying/selling alternatives, complete and incomplete scenarios, a plan when supported, calculation inputs, source/model provenance, location evidence and a historical-error screen. Candidate computation is bounded to up to eight buying and eight selling series; it is not a global optimum. Existing 20-crop empirical selection and the 208 current forecasts remain unchanged; no new crop data or real model evaluation was collected or run for this change.

Buy and deliver scenarios add procurement, capacity-constrained transport and handling. Same-day buy/sell scenarios use both compatible current forecasts. Sell-now scenarios for owned produce do not assume a purchase cost: revenue less delivery/handling gives net sale proceeds; profit remains null unless an acquisition cost is supplied. Storage scenarios never reuse today's selling price as a future selling price. No storage-for-profit plan is promoted without verified suitability/space, complete road legs and a separately validated future-price forecast.

Trips = ceiling(quantity quintals / user-entered vehicle capacity quintals). Freight is INR/tonne-km times total load tonnes and one-way distance; per-trip fixed/toll assumptions multiply by trip count. Fuel and vehicle-km calculations multiply distance by trips. These are alternative cost modes; fuel is never added to an inclusive freight rate. Return travel, legal truck restrictions, waiting, spoilage, financing and taxes remain unmodeled. Missing capacity/rate/access roads withhold route-dependent scenario costs. The maximum-distance constraint includes entered access legs, not invented straight-line roads.

The uncertainty screen is twice the saved crop-level development MAE times quantity. It flags close alternatives and margins within historical error; it is explicitly a heuristic, not a calibrated confidence interval or proof of statistically equal market performance. The daily model remains persistence. No frozen Phase 8/9 experiment, consumed target window or original model decision was changed or rerun.

Route alternatives are deduplicated only when their saved geometries match. Exact road geometry and computed cost differences explain the preferred saved route. Verified district-reference coordinates are now distinguished from their derived road snap coordinates and straight-line gaps; neither is represented as a verified mandi entrance. Market entrances remain unresolved. Storage maps use the actual existing OSM-reported facility point/area centroid with an unverified label and unknown entrance access, not a district point relabelled as a warehouse.

The unified warehouse endpoint `/api/v3/decisions/warehouse-catalog` retains all 168 existing IDs, operators, reported coordinates, source/snapshot, field-level verification, nominal versus available capacity and tariff fields. No similarly named facilities were newly merged. CWC/WDRA review did not produce a usable current facility-level register: CWC warehouse-list/tariff links returned errors, its accessible vacancy page was last updated April 22, 2021, and the supplied DFPD page did not expose facility records. No current capacity, suitability or tariff was imported from those pages. A destination-to-facility saved link is displayed directionally; it is not reversed into an unverified facility-to-destination route. Direct delivery can have fewer unknown inputs when fully costed; there is no validated evidence that holding covers additional storage costs.

Current weather context now includes forecast humidity and wind along with rain and temperature, using an independently versioned, unit-validated cache with the existing timeout/stale fallback. Facility weather uses its OSM-reported coordinates, clearly marked unverified and outdoor; it never implies indoor storage conditions. Heavy rain notices use the existing forecast threshold and do not assert road closure. Historical reanalysis, stitched forecast archives and model-run vintages remain distinct. Open-Meteo's individual-run archives offer a prospective collection route, but were not downloaded or scored here; no weather model is deployed without valid chronological evidence.

Source documentation reviewed:
- OSRM: https://project-osrm.org/docs/v26.6.1/http (route alternatives are not guaranteed; profiles depend on graph preparation).
- CWC regional offices: https://cewacor.in/CWCRegionalOffices
- WDRA / DFPD: https://dfpd.gov.in/warehousing-development-regulatory-authority/en
- OSM warehouses: https://wiki.openstreetmap.org/wiki/Tag:man_made%3Dwarehouse
- Open-Meteo historical reanalysis: https://open-meteo.com/en/docs/historical-weather-api
- Historical forecasts: https://open-meteo.com/en/docs/historical-forecast-api
- Individual model runs: https://open-meteo.com/en/docs/single-runs-api

### Manual refresh and optional Windows scheduling

Print a bounded plan, without network requests:

```powershell
Set-Location '<project-root>'
powershell -ExecutionPolicy Bypass -File Code\daily\run_update.ps1
```

To execute that reviewed allowance manually, append `-Execute`. Defaults are seven IST dates through today, 280 calls and 50 MB; credentials use the existing secret loader. Today's observations can be displayed independently, but the forecasting cutoff excludes them from today's features. Recent dates are rechecked for late reports with two matching complete responses; raw revisions stay immutable. Normalization is whitespace/NFKC plus the existing explicit commodity policy, never fuzzy market/variety merging. New preprocessing is `daily-recent-v3-normalized-vintages`; older sources and releases are retained. Latest verified complete partitions supersede prior operational records, including retractions; unchanged raw records retain earlier recorded availability where supported. Completed scopes and already-verified partitions resume without repeated spending. Empty reports never become zero-price observations.

The workflow builds the new release/batch before switching published pointers and restores the old pointers on a source/publication failure. It does not train a large model or run research evaluations. New pointer versions invalidate API snapshots; the browser refreshes the active estimates/scenario. The manual refresh, no-change idempotence, publication-failure rollback, retraction/late-report handling and immutable-vintage behavior are tested with synthetic sources. **No live price refresh was executed for this change and no scheduled task is active.** Optional Windows Task Scheduler can invoke the same PowerShell script with `-Execute` under a user-chosen trigger/account and approved allowance; registration is intentionally left to the user.

Verification of Trading v2: 139 safe backend tests passed, 32 frontend tests passed, and TypeScript/Vite production build passed. Browser checks confirmed the three synchronized tabs, a 25-quintal / 10-quintal-capacity three-trip delivery calculation, owned-produce net sale proceeds without fabricated acquisition profit, route geometry and warehouse candidate maps. The 390px viewport had no horizontal content overflow. Real-data API checks covered owned sales, maximum-distance withholding and the 168-facility catalog. The bounded PowerShell refresh command was checked in offline-plan mode only. No protected experiment was rerun; no files were staged, committed or pushed. Known remaining warnings are the existing large main frontend bundle and Starlette/httpx deprecation.
