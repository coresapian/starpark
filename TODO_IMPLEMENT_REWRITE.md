# LinkSpot Rewrite TODO

## In Progress
- [x] 1. Audit current backend, frontend, Electron, and test/build setup.
- [x] 2. Confirm safe rewrite touchpoints and avoid clobbering unrelated work.
- [x] 3. Add canonical backend math package for geodesy, time, TLE parsing, and orbital observation.
- [x] 4. Add golden/reference fixtures and focused backend math tests.
- [x] 5. Route satellite visibility and obstruction runtime through the new math package.
- [x] 6. Fix backend correctness issues uncovered in review.
- [x] 7. Unify request ID propagation.
- [x] 8. Make health checks report degraded services truthfully.
- [x] 9. Degrade heatmap road-mask failures to full-grid analysis instead of empty output.
- [x] 10. Isolate blocking geocoder work from async request paths.
- [x] 11. Introduce frontend React + TypeScript + Vite scaffolding for the new renderer.
- [x] 12. Add typed frontend state and service boundaries for API and Electron integration.
- [x] 13. Add Electron TypeScript scaffolding and typed preload contracts for the new shell.
- [x] 14. Add or update build/test entrypoints for backend math, frontend app, and Electron shell.
- [x] 15. Run focused verification and document remaining cutover work.

## Follow-On Cutover
- [x] Add in-repo near-Earth SGP4 propagation and remove the runtime `sgp4` dependency.
- [x] Cut Electron preload/settings over to emitted TypeScript runtime assets.
- [x] Make Electron prefer the built React renderer while embedding the legacy console for feature parity.
- [x] Implement the deep-space SGP4 branch for MEO/GEO resonance and low-inclination cases.
- [x] Switch Docker/static serving to the new frontend build output while keeping the legacy console mounted at `/legacy/`.
- [x] Port the Electron main process to TypeScript and switch the runtime entrypoint to `electron/dist/main.js`.
- [ ] Port the remaining mission-control feature set out of the embedded legacy console and into the React renderer.
- [ ] Remove superseded legacy math/helpers only after the new runtime is fully verified.
