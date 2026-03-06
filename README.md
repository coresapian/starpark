# StarPark

StarPark is a satellite visibility analysis and route planning platform.
It combines map data, building geometry, and satellite calculations to help users plan stronger connectivity.

[![Netlify Status](https://api.netlify.com/api/v1/badges/4a95f5dc-3907-4d8b-900d-73dc8a951b08/deploy-status)](https://app.netlify.com/projects/starpark/deploys)
[![Production](https://img.shields.io/badge/site-www.starpark.app-2ea44f)](https://www.starpark.app)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688)](https://fastapi.tiangolo.com/)

## Deployment Status

- Product name: StarPark
- Production domain: https://www.starpark.app
- Netlify project: starpark
- Netlify owner: Artificial-Me
- Netlify site id: 4a95f5dc-3907-4d8b-900d-73dc8a951b08
- Deploy source: GitHub
- Current note: configuration for StarPark deploy is in progress

## What StarPark Does

- Analyze satellite visibility for a point in time and location
- Render building-aware map overlays for coverage quality
- Generate route level connectivity insights along a path
- Expose a FastAPI backend for analysis, route, and health endpoints
- Serve a vanilla JavaScript frontend with Leaflet map visualization
- Provide an Electron desktop app shell

## Project Layout

| Path | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app entrypoint |
| `backend/routers/` | API routes |
| `backend/database/` | Database and spatial logic |
| `backend/models/schemas.py` | Pydantic request and response schemas |
| `frontend/index.html` | Frontend shell |
| `frontend/js/app.js` | Frontend app orchestrator |
| `frontend/js/api-client.js` | Frontend API client |
| `electron/main.js` | Electron main process |
| `docker-compose.yml` | Local service orchestration |
| `Makefile` | Common dev and ops commands |

## Local Development

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Git

### Quick Start

```bash
git clone <repository-url>
cd <repo-folder>
make up
```

Then open:

- Frontend: http://localhost
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

To stop services:

```bash
make down
```

## Common Commands

```bash
make help
make up
make down
make ps
make logs
make logs-service SERVICE=backend
make test
make lint
make format
make typecheck
make migrate
make db-shell
make seed
```

## Netlify Deployment

This repository contains a legacy static frontend in `frontend/` and an API backend that runs separately.

The Netlify configuration is committed and ready:

- `netlify.toml`: publishes the `frontend` directory with no build step
- `frontend/_redirects`: proxies API traffic and enables SPA fallback routing

Current redirect rules:

```text
/api/*  https://api.starpark.app/api/:splat  200
/*      /index.html                            200
```

If your backend host is different, update only the first line in `frontend/_redirects`.

## Self Hosted MacBook Backend

A hardened self host bundle is included:

- `docker-compose.selfhost.yml`
- `.env.selfhost.example`
- `scripts/selfhost/deploy.sh`
- `scripts/selfhost/install-launchd.sh`
- `scripts/selfhost/tunnel-pgrok.sh`
- `scripts/selfhost/install-pgrok-launchd.sh`
- `scripts/selfhost/app.starpark.selfhost.plist.template`
- `scripts/selfhost/app.starpark.pgrok.tunnel.plist.template`

Quick setup on your MacBook:

```bash
cp .env.selfhost.example .env.selfhost
nano .env.selfhost
./scripts/selfhost/deploy.sh
./scripts/selfhost/install-launchd.sh
./scripts/selfhost/install-pgrok-launchd.sh
```

Security defaults in this bundle:

- Backend listens on `127.0.0.1:8000` by default
- Postgres and Redis are not exposed on host ports
- Backend container runs with read only filesystem and dropped Linux capabilities
- `launchd` starts backend services on reboot/login via `ensure-up` mode
- `launchd` keeps the pgrok tunnel process alive with auto-restart

Recommended public routing for home hosting:

- Keep Netlify for `www.starpark.app`
- Route `api.starpark.app` through pgrok to the local backend
- Keep the `/api/*` redirect in `frontend/_redirects`

pgrok defaults in this bundle:

- Local pgrok repo path: `/Users/core/Documents/pgrok`
- Tunnel command: `scripts/selfhost/tunnel-pgrok.sh`
- Subdomain: `api` (set `PGROK_SUBDOMAIN` in `.env.selfhost` to change)
- Local target: `localhost:8000`
- Domain safety check: `EXPECTED_PGROK_DOMAIN=coresapian.com`

Before enabling the tunnel service, verify `~/.pgrok/config` points to your pgrok tunnel server and domain.
If pgrok is not built yet, run `/Users/core/Documents/pgrok/setup.sh client --rebuild`.

## Notes On Naming

The public product name is now StarPark.

Some internal defaults in Docker and database settings still use the `linkspot` name for compatibility.
This does not affect public branding or domain routing.

## Troubleshooting

### Services not starting

```bash
make ps
make logs
make logs-service SERVICE=backend
```

### Database connectivity checks

```bash
docker-compose -p linkspot exec postgres pg_isready -U linkspot -d linkspot
```

### Port conflict checks

If ports are busy, update host side ports in `docker-compose.yml`.

## Security Notes

- Change default credentials before production use
- Never commit secrets from `.env`
- Restrict database and cache exposure in production
- Enable HTTPS for all public traffic
- Keep backups and restore procedures tested

## Support

Please use the GitHub issue tracker for bugs and feature requests.
