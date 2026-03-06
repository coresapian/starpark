# LinkSpot TODO Review Queue

## Implementation Status (2026-02-19)
- [x] Phase 1 (P0 hardening) implemented across protocol, DB lifecycle, analysis validation, and config profile policies.
- [x] Phase 2 (service resilience) implemented for OSRM retries/fallback, route timeout budgets, satellite degradation handling, and dependency fallbacks.
- [x] Phase 3 (data integrity) implemented for visibility-schema normalization, coordinate/bbox guards, and safer Overture row-group filtering.
- [x] Phase 4 (frontend continuity) implemented for route backpressure/abort, idempotent overlay lifecycle, SW cache strategy hardening, and sky-plot render controls.
- [x] Phase 5 (ops/config) implemented for Electron settings validation, updater gating, and component-level backend diagnostics.
- [x] Phase 6 (observability) implemented for request context/error categorization and structured logging fields.

## Active TODO Insertion Sweep
- [x] 1) Add `TODO:` markers in `backend/data_pipeline.py` for external-data resilience gaps and geometry/cache edge cases.
- [x] 2) Add `TODO:` markers in `backend/database/connection.py` for lifecycle/cleanup and degraded-mode handling.
- [x] 3) Add `TODO:` markers in `backend/database/queries.py` for SQL construction, bulk-load validation, and cache invalidation robustness.
- [x] 4) Add `TODO:` markers in `backend/routers/analysis.py` for payload sanitization, timeout/cap limits, and degraded-path telemetry.
- [x] 5) Add `TODO:` markers in `backend/routers/satellites.py` for result shaping, observability, and cache staleness controls.
- [x] 6) Add `TODO:` markers in `backend/routers/health.py` for component isolation and faster async fan-out.
- [x] 7) Add `TODO:` markers in Electron runtime files:
  - `electron/main.js`
  - `electron/protocol-handler.js`
  - `electron/preload.js`
  - `electron/store.js`
  - `electron/settings.js`
  - `electron/menu.js`
  - `electron/tray.js`
  - `electron/updater.js`
- [x] 8) Add `TODO:` markers in `frontend/sw.js` for caching semantics and background sync implementation details.

## 1) P0 — Reliability and breakage risks
1. Add request sanitization and allow-list checks in `electron/protocol-handler.js` so proxying does not forward unsupported methods/headers or malformed backend URLs.
2. Guard all DB lifecycle edges in `backend/database/connection.py` (connect, close, recreate engine) and avoid silent continuation after failed engine setup.
3. Add defensive payload validation in `backend/routers/analysis.py` before cache keying, grid generation, and obstruction loops.
4. Make timeout and CORS policy explicit by deployment profile in `backend/config.py`.

## 2) P1 — Reliability and resilience
5. Add request timeout budgets and bounded fallback windows in `backend/osrm_client.py` and `backend/routers/route.py` for OSRM + external services.
6. Degrade gracefully in `backend/routers/satellites.py` when cache/engine returns partial or invalid satellite records.
7. Improve external-service fail-open behavior in `backend/data_pipeline.py` and `backend/dependencies.py` for Redis, OSM Overpass, and terrain fetches.
8. Add persistent/replay-safe queue semantics in `frontend/js/api-client.js` for queued offline requests.

## 3) P1 — Data quality and integrity
9. Normalize visibility schemas at boundary (`visible`, `is_visible`, `obstructed`) in `backend/routers/analysis.py` and frontend consumers (`frontend/js/sky-plot.js`, `frontend/js/intel-panel.js`).
10. Audit coordinate transforms and edge cases (antimeridian, poles, precision loss) in `backend/terrain_client.py`, `backend/data_pipeline.py`, and `backend/routers/analysis.py`.
11. Add attribution and source-fallback checks in `backend/overture_client.py` and `backend/routers/analysis.py` before trusting Overture/building output.

## 4) P2 — Performance and UX continuity
12. Add route request backpressure in `frontend/js/app.js` to avoid duplicate heatmap/route calls during high-frequency input.
13. Make map overlay lifecycle idempotent in `frontend/js/route-renderer.js` and `frontend/js/app.js` when map or layers are re-instantiated.
14. Add stale-while-revalidate and safer cache key strategy in `frontend/sw.js` to reduce stale reads and cache blowups.
15. Add visibility rendering dedupe for high-density sky plots in `frontend/js/sky-plot.js`.
16. Add route summary contract tests/guards for `frontend/index.html` and `frontend/js/route-renderer.js`.

## 5) P2 — Configuration and operations
17. Add schema-backed settings validation in `electron/store.js`, `electron/settings.js`, and `electron/preload.js` for backend URL + notification settings.
18. Add component-level diagnostics instead of all-or-nothing health in `electron/main.js` and `backend/routers/health.py`.
19. Add updater/launch gating in `electron/updater.js` and `electron/main.js` so network-dependent flows do not block startup.
20. Add mobile/accessibility fallbacks in `frontend/css/styles.css` and `frontend/index.html` for reduced motion and constrained viewports.

## 6) P3 — Observability and maintainability
21. Add context IDs and error-category tags in `backend/main.py`, `backend/routers/route.py`, and `backend/routers/analysis.py` for troubleshooting.
22. Add explicit TODOs for legacy-contract migration in `frontend/js/command-panel.js`, `frontend/js/intel-panel.js`, and `frontend/js/route-renderer.js`.
