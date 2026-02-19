# AGENTS.md

Operational guide for coding agents working in `LinkSpot`.

## Scope and Priority
- Applies to the whole repository.
- Follow explicit user instructions first, then this file.
- Keep changes minimal and consistent with existing architecture.

## Project Snapshot
- Product: satellite visibility analysis and route planning.
- Backend: FastAPI + async Python + PostGIS + Redis.
- Frontend: vanilla JS SPA + Leaflet + Canvas.
- Desktop: Electron app via `app://` protocol.
- Infra: Docker Compose orchestrated through `make`.

## Key Paths
- API entrypoint: `backend/main.py`
- Routers: `backend/routers/*.py`
- DI/singletons: `backend/dependencies.py`
- Schemas (Pydantic v2): `backend/models/schemas.py`
- DB/spatial logic: `backend/database/*.py`
- Frontend app shell: `frontend/js/app.js`
- Frontend API wrapper: `frontend/js/api-client.js`
- Electron main: `electron/main.js`
- Task commands: `Makefile`

## Build, Run, and Diagnostics

Use `make` first unless a more specific command is needed.

### Core lifecycle
```bash
make up
make down
make rebuild
make ps
make logs
make logs-service SERVICE=backend
```

### Quality checks
```bash
make test
make test-coverage
make lint
make format
make typecheck
```

### Database/data
```bash
make migrate
make migrate-create MESSAGE="describe change"
make db-shell
make seed
```

### Running a single test (important)
Run one file:
```bash
docker-compose -p linkspot exec backend python -m pytest test_api.py -v
```

Run one class or method:
```bash
docker-compose -p linkspot exec backend python -m pytest test_ray_casting.py::TestClassName::test_method -v
```

If path-sensitive, execute from `backend/` in the container context.

### Electron
```bash
npm start
npm run build
npm run build:universal
```

## Testing Expectations
- Prefer focused tests for touched code, then expand if needed.
- Backend edits should include at least one targeted pytest run.
- API contract changes should update both schemas and route tests.
- Do not rely only on manual `/docs` validation.

## Python Conventions

### Language and typing
- Python 3.11+ style (`list[str]`, `str | None`, etc.).
- Add type hints for function signatures and meaningful locals.
- Use `Any` only at integration boundaries.
- Prefer explicit return types on public helpers/endpoints.

### Imports
- Group imports as stdlib, third-party, then local.
- Keep imports deterministic and `isort` friendly.
- Prefer absolute imports from backend-root modules.

### Formatting and static checks
- Formatter: `black`.
- Import sorter: `isort`.
- Linter: `flake8`.
- Type checker: `mypy`.
- Keep code Black-compatible; do not hand-format against it.

### Naming
- Files/modules: `snake_case.py`.
- Functions/variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Enum members use existing style (e.g., `EXCELLENT`, `GOOD`).

### API and schema patterns
- Validate API request/response through models in `backend/models/schemas.py`.
- Keep routers thin; push logic to engines/adapters/services.
- Use FastAPI `Depends(...)` for dependency injection.
- Prefer RFC7807-style errors via `ProblemDetail`.

### Async and performance
- Treat backend I/O as async-first (DB, Redis, HTTP).
- Avoid blocking calls in async routes; use `asyncio.to_thread` for sync-heavy work.
- Respect timeout budgets from `backend/config.py`.

### Error handling and logging
- Raise `HTTPException` with clear status and concise detail.
- Catch narrow exceptions where possible; avoid broad `except` unless adding context.
- Include `request_id` in request-path logs when available.
- Never log secrets or full sensitive payloads.

### Configuration
- Read settings from `backend/config.py` (`settings` singleton).
- Add new env vars to `Settings` with validation.
- Use safe defaults and stricter production constraints.

## Frontend JavaScript Conventions
- Keep vanilla JS class-based structure in `frontend/js/`.
- Preserve `LinkSpotApp` as stateful orchestrator.
- Centralize backend calls in `APIClient`; avoid ad-hoc fetches.
- Validate numeric inputs (`Number.isFinite`, parse-and-guard).
- Surface network/offline/timeout failures with clear user feedback.

## Electron Conventions
- Maintain secure defaults: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`.
- Expose renderer capabilities via preload bridge APIs.
- Keep IPC handlers small, validated, and defensive.

## Domain Conventions
- Coordinates are WGS84 lat/lon unless explicitly documented otherwise.
- Distances/radii in payloads are meters (`*_m`).
- Preserve GeoJSON contracts expected by the frontend.

## Change Management for Agents
- Make minimal, targeted edits.
- Do not rewrite large files for small behavior changes.
- Preserve existing license/header blocks in Python files.
- Update tests/docs when behavior or API contracts change.

## Cursor/Copilot Rules
- `.cursor/rules/`: not present.
- `.cursorrules`: not present.
- `.github/copilot-instructions.md`: not present.

If these files are added later, treat them as higher-priority agent instructions.
