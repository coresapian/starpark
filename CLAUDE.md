# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LinkSpot is a satellite visibility analysis platform that identifies optimal locations for satellite dishes by analyzing sky obstruction from building shadows. It uses ray-casting for obstruction detection, Skyfield/SGP4 for satellite propagation, and PostGIS for spatial queries. The frontend is a Leaflet-based SPA with Canvas rendering for heat maps and sky plots. The app runs as both a web app (Docker/Nginx) and a native macOS desktop app (Electron).

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) / PostgreSQL+PostGIS / Redis
- **Frontend**: Vanilla JS (ES2020+) / Leaflet 1.9.4 / HTML5 Canvas / PWA with Service Worker
- **Desktop**: Electron 28 with electron-builder (macOS DMG/ZIP)
- **Infrastructure**: Docker Compose / Nginx / Gunicorn+Uvicorn

## Common Commands

All Docker commands use `make` and run via Docker Compose:

```bash
make up                  # Start all services (dev mode with hot reload)
make down                # Stop all services
make rebuild             # Full rebuild (no-cache) and restart
make logs                # View all logs
make logs-service SERVICE=backend  # View specific service logs
make shell               # Open backend container shell
make ps                  # Show running containers

make test                # Run pytest (backend)
make test-coverage       # pytest with HTML coverage report
make lint                # black --check, isort --check, flake8
make format              # Auto-format with black and isort
make typecheck           # Run mypy

make migrate             # Run Alembic migrations
make migrate-create MESSAGE="description"  # Create new migration
make db-shell            # Open psql shell
make seed                # Seed test data
```

Run a single test file inside the backend container:
```bash
docker-compose -p linkspot exec backend python -m pytest test_api.py -v
docker-compose -p linkspot exec backend python -m pytest test_ray_casting.py::TestClassName::test_method -v
```

Electron desktop app:
```bash
npm start                # Run Electron dev app
npm run build            # Build macOS DMG
npm run build:universal  # Build Universal (Intel + ARM)
```

**Local access after `make up`**: Frontend at http://localhost, API at http://localhost:8000, Swagger docs at http://localhost:8000/docs

## Architecture

```
Browser/Electron → Nginx (port 80, static files + API proxy)
                     → FastAPI (port 8000)
                         ├── routers/analysis.py    → heatmap & position analysis endpoints
                         ├── routers/satellites.py   → constellation query endpoints
                         ├── routers/health.py       → health checks
                         ├── ray_casting_engine.py   → azimuth-based obstruction detection
                         ├── satellite_engine.py     → Skyfield SGP4 orbit propagation
                         ├── grid_analyzer.py        → heatmap grid point analysis
                         ├── data_pipeline.py        → ETL for building/satellite data
                         ├── database/              → SQLAlchemy models, queries, Alembic
                         ├── coordinates/           → ENU transforms, azimuth/elevation, geohash
                         └── cache/redis_client.py  → async Redis caching
```

**Electron path**: `electron/main.js` → custom `app://` protocol (`protocol-handler.js`) → serves frontend files locally and proxies `/api/` to backend. Context isolation is on; all renderer↔main communication goes through `preload.js` via `contextBridge`.

**External data sources**: CelesTrak (TLE data, 4h cache), Nominatim (geocoding), Overture Maps (building footprints, 24h cache), OpenStreetMap (map tiles)

## Key Backend Patterns

- **Fully async**: all DB (asyncpg), Redis (aioredis), and HTTP (httpx) operations use async/await
- **Dependency injection** via FastAPI's `Depends()` with global singleton pools in `dependencies.py`
- **Adapter pattern**: sync engines (`SatelliteEngine`, `DataPipeline`) wrapped with `asyncio.to_thread()` for async router use
- **Configuration** via Pydantic Settings in `config.py` — all settings from environment variables
- **Structured JSON logging** with request IDs via structlog; RFC 7807 ProblemDetail error responses
- **Pydantic schemas** for all request/response validation in `models/schemas.py`
- **Spatial math** in `coordinates/` — ENU transforms, azimuth/elevation, geodetic distance, geohash utilities; vectorized with NumPy
- **Caching**: geohash-based Redis keys (`buildings:{geohash}`, `tles:{constellation}`, `analysis:{hash}`)
- **Multi-stage Dockerfile**: base → development (hot reload, dev tools) → production (non-root, 4-worker Gunicorn)

## Key Frontend Patterns

- Class-based SPA (`LinkSpotApp` in `js/app.js`) with state via instance properties
- `js/api-client.js` wraps all `/api/v1/` fetch calls with retry logic, timeout handling, offline detection
- `js/sky-plot.js` renders azimuth/elevation polar plots on Canvas with High DPI support
- PWA: `sw.js` uses network-first for API, cache-first for static assets; versioned caches (`linkspot-static-v2`)
- CSS custom properties define a colorblind-safe palette, z-index layers, and spacing scale
- Z-index layers: Map(1) → Controls(100) → Overlay(200) → Modal(300) → Toast(400) → Loading(500)

## Electron App

- `electron/main.js` — window management, menu registration, tray, auto-updater
- `electron/protocol-handler.js` — custom `app://` scheme serves frontend files with MIME detection, injects CSP headers, proxies API requests to configurable backend URL
- `electron/preload.js` — exposes `window.electronAPI` via contextBridge (settings, location, notifications, menu event listeners)
- `electron/store.js` — persistent settings via electron-store (backendURL, notifications, windowBounds)
- `electron/get-location.swift` — native macOS CLLocationManager for geolocation
- Build config in `electron-builder.yml`: macOS DMG+ZIP, hardened runtime, GitHub releases auto-update

## Docker Services

Five services on custom bridge network (172.20.0.0/16):
- **postgres**: PostGIS 15-3.3, 2GB memory limit, initialized via `scripts/init-db.sh`
- **redis**: 7-alpine with AOF persistence, LRU eviction at 512MB
- **backend**: FastAPI with hot reload (dev) or multi-worker Gunicorn (prod)
- **frontend**: Nginx 1.25-alpine with gzip, SPA routing, API proxy, security headers
- **backup**: On-demand PostgreSQL backup (profile: backup)

## Requirements Files

Backend dependencies split across:
- `requirements_api.txt` — FastAPI, Uvicorn, Pydantic, Gunicorn, Redis
- `requirements_db.txt` — SQLAlchemy, asyncpg, Alembic, GeoAlchemy2, Shapely
- `requirements_satellite.txt` — Skyfield, SGP4, NumPy
- `requirements_raycasting.txt` — NumPy, Shapely, GeoPandas, PyProj
- `requirements_data.txt` — Pandas, PyArrow, Rasterio, boto3
- `coordinates/requirements_coords.txt` — PyProj, NumPy, pygeohash

## Code Style

- Type hints throughout (Python 3.11+)
- Formatting: Black + isort; linting: flake8; type checking: mypy
- BSD 3-Clause License headers on Python files

## Notable Files

- `linkspot_v1.html` — original single-file monolithic prototype (958 lines); superseded by the modular architecture but kept for reference
- `scripts/init-db.sh` — creates PostGIS extensions, schema tables, spatial indexes, optional seed data
- `scripts/backup.sh` — database backup with compression, retention policy, manifest generation
