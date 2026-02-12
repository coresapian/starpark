# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LinkSpot is a satellite visibility analysis platform that identifies optimal locations for satellite dishes by analyzing sky obstruction from building shadows. It uses ray-casting for obstruction detection, Skyfield/SGP4 for satellite propagation, and PostGIS for spatial queries. The frontend is a Leaflet-based SPA with Canvas rendering for heat maps and sky plots.

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async) / PostgreSQL+PostGIS / Redis
- **Frontend**: Vanilla JS (ES2020+) / Leaflet 1.9.4 / HTML5 Canvas / PWA with Service Worker
- **Infrastructure**: Docker Compose / Nginx / Gunicorn+Uvicorn

## Common Commands

All commands use `make` and run via Docker Compose:

```bash
make up                  # Start all services (dev mode with hot reload)
make down                # Stop all services
make rebuild             # Full rebuild and restart
make logs                # View all logs
make logs-service SERVICE=backend  # View specific service logs
make shell               # Open backend container shell

make test                # Run pytest (backend)
make test-coverage       # pytest with HTML coverage report
make lint                # black --check, isort --check, flake8
make format              # Auto-format with black and isort
make typecheck           # Run mypy

make migrate             # Run Alembic migrations
make migrate-create MESSAGE="description"  # Create new migration
make db-shell            # Open psql shell
make seed                # Seed test data

make prod-build          # Production Docker build
make prod-up             # Start production services
```

**Local access after `make up`**: Frontend at http://localhost, API at http://localhost:8000, Swagger docs at http://localhost:8000/docs

## Architecture

```
Browser → Nginx (port 80, static files + API proxy)
            → FastAPI (port 8000)
                ├── routers/analysis.py    → heatmap & position analysis endpoints
                ├── routers/satellites.py   → constellation query endpoints
                ├── routers/health.py       → health checks
                ├── ray_casting_engine.py   → azimuth-based obstruction detection
                ├── satellite_engine.py     → Skyfield SGP4 orbit propagation
                ├── grid_analyzer.py        → heatmap grid point analysis
                ├── data_pipeline.py        → ETL for building/satellite data
                ├── database/              → SQLAlchemy models, queries, Alembic migrations
                └── cache/redis_client.py  → async Redis caching
```

**External data sources**: CelesTrak (TLE data, 4h cache), Nominatim (geocoding), Overture Maps (building footprints, 24h cache), OpenStreetMap (map tiles)

## Key Backend Patterns

- **Fully async**: all DB (asyncpg), Redis (aioredis), and HTTP (httpx) operations use async/await
- **Dependency injection** via FastAPI's `Depends()` with global connection pools in `dependencies.py`
- **Configuration** via Pydantic Settings in `config.py` — all settings come from environment variables
- **Structured JSON logging** with request IDs via structlog
- **Pydantic schemas** for all request/response validation in `models/schemas.py`
- **Spatial math** in `coordinates/` — ENU transforms, azimuth/elevation, geodetic distance, geohash utilities

## Key Frontend Patterns

- Class-based SPA (`LinkSpotApp` in `js/app.js`) with state via instance properties
- `js/api-client.js` wraps all `/api/v1/` fetch calls
- `js/sky-plot.js` renders azimuth/elevation polar plots on Canvas
- PWA support: `sw.js` (service worker) + `manifest.json`

## Docker Services

Five services on custom bridge network (172.20.0.0/16):
- **postgres**: PostGIS 15-3.3, 2GB memory limit
- **redis**: 7-alpine with AOF persistence, LRU eviction at 512MB
- **backend**: FastAPI with hot reload (dev) or multi-worker Gunicorn (prod)
- **frontend**: Nginx 1.25-alpine with gzip compression and SPA routing
- **backup**: On-demand PostgreSQL backup (profile: backup)

## Requirements Files

Backend dependencies are split across multiple requirements files:
- `requirements_api.txt` — FastAPI, async, validation
- `requirements_db.txt` — PostgreSQL, PostGIS, SQLAlchemy
- `requirements_satellite.txt` — Skyfield, SGP4, orbital mechanics
- `requirements_raycasting.txt` — Shapely, NumPy for geometry
- `requirements_data.txt` — Data processing utilities
- `coordinates/requirements_coords.txt` — Coordinate module dependencies

## Code Style

- All Python files carry BSD 3-Clause License headers
- Type hints throughout (Python 3.11+)
- Formatting: Black + isort; linting: flake8; type checking: mypy
