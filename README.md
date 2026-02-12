# ðŸ“¡ Starlink Park â€” Sky-View Advisor

A browser-based tool that helps you find optimal parking spots for vehicles with roof-mounted Starlink dishes. It analyzes building shadows based on real sun position data and OpenStreetMap building footprints to highlight areas with clear sky visibility.

![Status](https://img.shields.io/badge/status-prototype-00d4ff)
![License](https://img.shields.io/badge/license-MIT-22e87e)
![Stack](https://img.shields.io/badge/stack-vanilla%20JS%20%2B%20Leaflet-ffaa22)

---

## How It Works

Starlink dishes require a wide, unobstructed view of the sky to maintain a reliable connection to the satellite constellation. In urban environments, tall buildings cast shadows that correspond to blocked sky sectors â€” if a building blocks the sun from a point on the ground, it also blocks a significant portion of the sky from that same point.

This app combines three data sources to visualize where those obstructions are:

1. **OpenStreetMap building data** â€” real building footprints with height/floor metadata, fetched via the Overpass API
2. **Solar position calculations** â€” astronomical model computing sun elevation and azimuth for any date, time, and geographic coordinate
3. **Shadow projection geometry** â€” each building's footprint is extruded into a shadow polygon based on the sun angle, then rendered onto a canvas overlay

The result is a color-coded map showing where you can park with confidence that your Starlink dish will have a clear view.

---

## Features

- **Location search** â€” Nominatim geocoding to jump to any address or city
- **Geolocation** â€” auto-centers on your current position (with permission)
- **Real building data** â€” fetches actual building footprints and heights from OpenStreetMap via the Overpass API with automatic failover across three endpoints
- **Accurate solar model** â€” calculates sun elevation and azimuth using solar declination, equation of time, and hour angle for any date/time/location
- **Time slider** â€” scrub through the full 24-hour day and watch shadows shift in real time (debounced at ~25fps)
- **Date picker** â€” plan ahead for a specific day to account for seasonal sun angle changes
- **Canvas-rendered overlay** â€” all shadows, fringes, and clear zones drawn on a single hardware-accelerated canvas layer for smooth performance
- **Sun arc widget** â€” miniature canvas indicator showing the sun's position on a semicircular arc
- **Building tooltips** â€” hover any building to see its estimated height and floor count

### Map Legend

| Color | Meaning |
|-------|---------|
| ðŸŸ¢ Green dots | **Clear sky** â€” optimal Starlink reception, park here |
| ðŸŸ¡ Amber fringe | **Partial shadow** â€” fair reception, some sky obstruction |
| ðŸ”´ Red polygons | **Building shadow** â€” poor reception, sky blocked |
| ðŸ”µ Gray outlines | **Building footprints** â€” the structures themselves |

---

## Quick Start

This is a single-file HTML application with no build step required.

**Option A â€” Open directly:**
```
Open starlink-parking.html in any modern browser
```

**Option B â€” Local server (avoids potential CORS issues):**
```bash
# Python
python3 -m http.server 8000

# Node
npx serve .
```
Then visit `http://localhost:8000/starlink-parking.html`.

### Usage

1. Allow location access when prompted (or search for a location manually)
2. Pan/zoom the map to the area where you want to park
3. Click **âŸ Scan Area** to fetch building data for the visible area
4. Use the **time slider** to see how shadows change throughout the day
5. Look for **green dots** â€” those are your best parking spots
6. Change the **date** to plan for a future day

---

## Technical Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                  starlink-parking.html           â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                  â”‚
â”‚  SolarCalc          Pure astronomical model       â”‚
â”‚  â”œâ”€ dayOfYear()     Day number for declination    â”‚
â”‚  â”œâ”€ declination     Earth axial tilt correction   â”‚
â”‚  â”œâ”€ equationOfTime  Orbital eccentricity fix      â”‚
â”‚  â””â”€ getSunPosition  â†’ { elevation, azimuth }     â”‚
â”‚                                                  â”‚
â”‚  Overpass API       GET with failover chain       â”‚
â”‚  â”œâ”€ overpass-api.de (primary)                     â”‚
â”‚  â”œâ”€ overpass.kumi.systems (fallback 1)            â”‚
â”‚  â””â”€ maps.mail.ru (fallback 2)                    â”‚
â”‚                                                  â”‚
â”‚  parseBuildings()   OSM â†’ building objects        â”‚
â”‚  â”œâ”€ height from tags.height                       â”‚
â”‚  â”œâ”€ height from building:levels Ã— 3.5m            â”‚
â”‚  â””â”€ height from HEIGHT_DEFAULTS lookup table      â”‚
â”‚                                                  â”‚
â”‚  ShadowCanvasOverlay   L.Layer.extend()           â”‚
â”‚  â”œâ”€ draw()             Main render loop           â”‚
â”‚  â”‚  â”œâ”€ Amber fringe    Expanded shadow envelope   â”‚
â”‚  â”‚  â”œâ”€ Red shadows     Footprintâ†’projection poly  â”‚
â”‚  â”‚  â””â”€ Green dots      Grid-sampled clear zones   â”‚
â”‚  â””â”€ pointInPolygon()   Ray-casting hit test       â”‚
â”‚                                                  â”‚
â”‚  Leaflet Map        Dark-themed OSM tiles         â”‚
â”‚  â””â”€ buildingLayer   L.layerGroup with tooltips    â”‚
â”‚                                                  â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### Shadow Projection Algorithm

For each building at a given sun position:

1. Calculate shadow length: `height / tan(sun_elevation)`
2. Calculate shadow direction: `sun_azimuth + 180Â°` (shadows fall opposite the sun)
3. Convert the shadow offset from meters to lat/lon degrees using local scale factors
4. Build a closed polygon by walking the building footprint forward, then the projected (offset) footprint in reverse â€” this produces the correct trapezoidal shadow shape
5. Apply a 20% centroid-expansion to generate the amber "partial shadow" fringe

### Clear Zone Detection

A regular grid (~28m spacing) is sampled across the viewport. Each grid point is tested against all building footprints and shadow polygons using ray-casting point-in-polygon checks. Points that aren't inside any building or shadow are rendered as green dots.

### Building Height Estimation

Heights are resolved in priority order:

1. `height` tag (explicit meters, e.g., `height=45`)
2. `building:levels` tag Ã— 3.5m per floor
3. Lookup table keyed by `building` type (e.g., `office` â†’ 24m, `shed` â†’ 3m)
4. Default fallback: 12m (~3 stories)

---

## Dependencies

All loaded via CDN â€” no `npm install` required.

| Library | Version | Purpose |
|---------|---------|---------|
| [Leaflet](https://leafletjs.com/) | 1.9.4 | Interactive map rendering |
| [OpenStreetMap Tiles](https://www.openstreetmap.org/) | â€” | Base map imagery |
| [Overpass API](https://overpass-api.de/) | â€” | Building footprint queries |
| [Nominatim](https://nominatim.openstreetmap.org/) | â€” | Geocoding / location search |
| [Google Fonts](https://fonts.google.com/) | â€” | Chakra Petch + IBM Plex Mono |

---

## Limitations & Caveats

- **Height data is estimated.** Most OSM buildings lack explicit height tags â€” the app uses heuristics based on building type and floor count, which may be inaccurate.
- **No terrain model.** Hills, slopes, and elevation changes are not accounted for â€” shadows are projected on a flat plane.
- **No tree coverage.** Trees are a major source of sky obstruction but aren't included in this analysis. Always verify in-person.
- **Simplified shadow geometry.** Buildings are treated as flat-roofed extrusions. Complex roof shapes, domes, spires, and setbacks are not modeled.
- **Overpass rate limits.** The Overpass API has usage limits â€” scanning very dense areas or scanning too frequently may return errors. The app includes automatic failover to two backup endpoints.
- **Solar model precision.** The astronomical calculations are accurate to within ~1Â° for most practical purposes but don't account for atmospheric refraction or sub-minute precision.
- **Starlink FOV simplification.** The app uses sun shadow angle as a proxy for sky obstruction. Starlink dishes actually need a wide cone of sky (~100Â° field of view), not just the solar vector â€” this tool shows the worst-case obstruction direction, not a full sky hemisphere analysis.

---

## Browser Support

Tested in Chrome, Firefox, Safari, and Edge (all modern versions). Requires:
- ES2020+ (optional chaining, nullish coalescing)
- Canvas 2D API
- Geolocation API (optional)

---

## License

MIT

## LinkSpot - Docker Compose Deployment

Satellite Tracking & Building Visualization Platform

[![Docker](https://img.shields.io/badge/Docker-Compose-blue)](https://docs.docker.com/compose/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791)](https://www.postgresql.org/)
[![PostGIS](https://img.shields.io/badge/PostGIS-3.3-3D7E3D)](https://postgis.net/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D)](https://redis.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688)](https://fastapi.tiangolo.com/)

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Services](#services)
- [Configuration](#configuration)
- [Development](#development)
- [Production Deployment](#production-deployment)
- [Database Management](#database-management)
- [Backup & Restore](#backup--restore)
- [Troubleshooting](#troubleshooting)

## Overview

LinkSpot is a satellite tracking and building visualization platform that enables users to:

- Track satellite positions in real-time using TLE data
- Visualize buildings on an interactive map
- Calculate satellite visibility from building locations
- Determine potential communication links between buildings

### Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Backend API | FastAPI (Python) | 3.11+ |
| Spatial Database | PostgreSQL + PostGIS | 15 + 3.3 |
| Cache | Redis | 7.x |
| Frontend | Leaflet + Canvas | - |
| Web Server | Nginx | 1.25 |
| Deployment | Docker Compose | 2.x+ |

## Prerequisites

### System Requirements

- **RAM**: 4-8 GB (8 GB recommended for production)
- **Disk**: 50-100 GB (depending on data coverage)
- **CPU**: 2+ cores
- **OS**: Linux, macOS, or Windows with WSL2

### Software Requirements

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- Git

### Verify Installation

```bash
docker --version
docker-compose --version
git --version
```

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd linkspot
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit configuration (optional)
nano .env
```

### 3. Start Services

```bash
# Using Make (recommended)
make up

# Or using Docker Compose directly
docker-compose up -d
```

### 4. Access the Application

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost | Main application |
| Backend API | http://localhost:8000 | API endpoints |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Health Check | http://localhost:8000/health | Service health |

### 5. Stop Services

```bash
make down
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LinkSpot Architecture                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────┐      ┌─────────────┐      ┌─────────────────────┐
│   Client    │──────▶│   Nginx     │──────▶│   FastAPI Backend   │
│  (Browser)  │◀──────│  (Port 80)  │◀──────│    (Port 8000)      │
└─────────────┘      └─────────────┘      └─────────────────────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          │                        │                        │
                          ▼                        ▼                        ▼
                   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                   │ PostgreSQL  │         │    Redis    │         │ External    │
                   │  + PostGIS  │         │   (Cache)   │         │    APIs     │
                   │ (Port 5432) │         │ (Port 6379) │         │  (TLE Data) │
                   └─────────────┘         └─────────────┘         └─────────────┘
```

### Service Communication

```
Network: linkspot-network (172.20.0.0/16)

┌──────────────────────────────────────────────────────────────┐
│  Service        │  Internal DNS      │  Ports                │
├──────────────────────────────────────────────────────────────┤
│  postgres       │  postgres:5432     │  5432 (host)          │
│  redis          │  redis:6379        │  6379 (host)          │
│  backend        │  backend:8000      │  8000 (host)          │
│  frontend       │  frontend:80       │  80 (host)            │
└──────────────────────────────────────────────────────────────┘
```

## Services

### PostgreSQL + PostGIS

- **Image**: `postgis/postgis:15-3.3`
- **Purpose**: Spatial database for buildings and satellite data
- **Data Volume**: `postgres_data`
- **Health Check**: `pg_isready`

### Redis

- **Image**: `redis:7-alpine`
- **Purpose**: Cache for TLE data and building data
- **Persistence**: AOF enabled
- **Memory Limit**: 512 MB with LRU eviction

### FastAPI Backend

- **Build**: `./backend/Dockerfile`
- **Purpose**: REST API for satellite calculations
- **Features**: Hot reload (dev), multi-worker (prod)
- **Health Check**: `/health` endpoint

### Nginx Frontend

- **Build**: `./frontend/Dockerfile`
- **Purpose**: Static file server + API proxy
- **Features**: Gzip compression, caching, SPA routing

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and customize:

```bash
# Database
DATABASE_URL=postgresql://linkspot:password@postgres:5432/linkspot
POSTGRES_DB=linkspot
POSTGRES_USER=linkspot
POSTGRES_PASSWORD=changeme

# Redis
REDIS_URL=redis://redis:6379/0

# Application
APP_ENV=development
LOG_LEVEL=INFO
DEBUG=true

# Cache TTL (seconds)
TLE_CACHE_TTL=14400        # 4 hours
BUILDING_CACHE_TTL=86400   # 24 hours

# Satellite Settings
MIN_ELEVATION=25.0
SATELLITE_THRESHOLD=4
```

### Resource Limits

Default resource limits in `docker-compose.yml`:

| Service | Memory Limit | Memory Reserved |
|---------|--------------|-----------------|
| postgres | 2 GB | 512 MB |
| redis | 512 MB | 128 MB |
| backend | 1 GB | 256 MB |
| frontend | 256 MB | 64 MB |

## Development

### Available Make Commands

```bash
make help              # Show all commands
make build             # Build all containers
make up                # Start services
make down              # Stop services
make logs              # View logs
make logs-service SERVICE=backend  # View specific service logs
make shell             # Open backend shell
make test              # Run tests
make migrate           # Run database migrations
make backup            # Create database backup
make format            # Format code
make lint              # Run linters
```

### Development Mode

```bash
# Start in development mode (hot reload enabled)
make up

# View backend logs
make logs-service SERVICE=backend

# Run tests
make test

# Open backend shell
make shell
```

### Production Mode

```bash
# Build for production
make prod-build

# Start production services
make prod-up

# Or combined
make prod-deploy
```

## Database Management

### Initialize Database

The database is automatically initialized on first startup via `scripts/init-db.sh`.

### Manual Migration

```bash
# Run migrations
make migrate

# Create new migration
make migrate-create MESSAGE="add new table"

# Reset database (WARNING: data loss)
make db-reset
```

### PostgreSQL Shell

```bash
make db-shell
```

### Seed Test Data

```bash
make seed
```

## Backup & Restore

### Create Backup

```bash
# Create backup (runs backup container)
make backup

# Or manually
docker-compose --profile backup run --rm backup
```

Backups are stored in `./backups/` with timestamp:
- `linkspot_postgres_YYYYMMDD_HHMMSS.sql.gz` - Full database backup
- `linkspot_schema_YYYYMMDD_HHMMSS.sql.gz` - Schema-only backup
- `backup_manifest_YYYYMMDD_HHMMSS.json` - Backup metadata

### Restore Backup

```bash
# Restore from backup file
gunzip -c backups/linkspot_postgres_latest.sql.gz | \
    docker-compose exec -T postgres psql -U linkspot -d linkspot
```

### Automated Backups

Add to crontab for daily backups:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * cd /path/to/linkspot && make backup
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status
make ps

# View logs
make logs

# Check specific service
make logs-service SERVICE=postgres
```

### Database Connection Issues

```bash
# Check PostgreSQL health
docker-compose exec postgres pg_isready -U linkspot

# Reset database
make db-reset
make migrate
```

### Port Conflicts

If ports are already in use, modify `docker-compose.yml`:

```yaml
ports:
  - "8080:80"      # Change host port
  - "8001:8000"    # Change host port
  - "5433:5432"    # Change host port
  - "6380:6379"    # Change host port
```

### Clean Start

```bash
# Remove all containers and volumes
make clean-all

# Rebuild and start
make rebuild
```

### Common Issues

| Issue | Solution |
|-------|----------|
| `permission denied` | Run with `sudo` or add user to docker group |
| `port already allocated` | Change ports in docker-compose.yml |
| `database does not exist` | Run `make db-reset` then `make migrate` |
| `out of memory` | Increase Docker memory limit or reduce container limits |
| `slow performance` | Check resource limits, consider increasing RAM |

### Health Checks

All services include health checks:

```bash
# Check all services
docker-compose ps

# Manual health check
curl http://localhost:8000/health
curl http://localhost/health
```

### Getting Help

```bash
# View all make commands
make help

# Check Docker Compose config
docker-compose config

# Inspect network
docker network inspect linkspot_linkspot-network
```

## Security Notes

1. **Change default passwords** in `.env` before production deployment
2. **Do not commit `.env` file** to version control
3. **Use HTTPS** in production (configure reverse proxy)
4. **Restrict database access** using firewall rules
5. **Regular backups** are essential for data protection

## License

[Your License Here]

## Support

For issues and feature requests, please use the GitHub issue tracker.
