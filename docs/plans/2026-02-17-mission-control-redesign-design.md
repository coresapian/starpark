# LinkSpot Mission Control Redesign

**Date**: 2026-02-17
**Status**: Approved
**Scope**: Complete frontend visual overhaul + backend fixes + new route planning feature

---

## 1. Overview

Redesign LinkSpot from a basic map-centric SPA into a full sci-fi tactical "Mission Control" interface. Simultaneously fix backend stubs/silent failures and add a new mission planning feature for route-based satellite connectivity analysis.

### Goals

- Replace the generic prototype UI with an aggressive dark tactical/HUD aesthetic
- Add mission planning: enter a destination, get a route with optimal parking spots for satellite internet
- Wire up stubbed backend components (terrain, constellation metadata)
- Surface data quality issues to the user instead of silently degrading

---

## 2. Layout Architecture

Three persistent zones plus status bar and timeline:

```
┌──────────────────────────────────────────────────────────────────┐
│  STATUS BAR  (system health, data sources, connection, clock)    │
├────────────┬─────────────────────────────────┬───────────────────┤
│            │                                 │                   │
│  COMMAND   │                                 │   INTEL PANEL     │
│  SIDEBAR   │          MAP VIEWPORT           │                   │
│  (~280px)  │                                 │   (~360px)        │
│            │     (Leaflet + heatmap +        │  Sky Plot         │
│  Search    │      building overlays +        │  Satellite List   │
│  Params    │      target marker +            │  Obstruction      │
│  Mission   │      route rendering)           │  Stats            │
│  Stats     │                                 │  Data Quality     │
│            │                                 │  Mission Brief    │
│            │                                 │                   │
├────────────┴─────────────────────────────────┴───────────────────┤
│  TIMELINE BAR  (24hr scrubber, play/pause, radar sweep style)    │
└──────────────────────────────────────────────────────────────────┘
```

- **Status bar** (~32px): Backend connection, data source indicators (buildings/terrain/satellites/routing), GPS lock, UTC clock
- **Command sidebar** (~280px, left): Two tabs — ANALYSIS (search, params) and MISSION (origin/destination, waypoint list)
- **Map viewport** (fills center): Leaflet with heatmap overlay, building footprints, route polyline, waypoint markers, target crosshair
- **Intel panel** (~360px, right): Sky plot, satellite list, obstruction summary, data quality, mission brief/summary
- **Timeline bar** (~48px): Full-width 24hr time scrubber with play/pause, styled as radar sweep

**Responsive**: Below 1024px, sidebar and intel panel collapse to slide-out drawers via hamburger/tab icons.

---

## 3. Visual Design Language

### Color Palette

| Token | Hex | Use |
|-------|-----|-----|
| bg-primary | #0a0a0f | Main background |
| bg-panel | #0d1117 | Panel backgrounds |
| border-bezel | #1a3a3a | Panel borders (double-line bezel) |
| accent-primary | #00ff88 | Key data, radar elements, phosphor green |
| accent-warning | #ffaa00 | Marginal zones, warnings |
| accent-danger | #ff3333 | Dead zones, errors, critical alerts |
| text-primary | #eaeef2 | Headings, important text |
| text-body | #c0c8d0 | Body text, labels |
| text-muted | #3a3f47 | Inactive elements, gridlines |

### Typography

- **Data/coordinates**: JetBrains Mono — all numerical readouts, coordinates, counts
- **Labels/headings**: Inter or system sans-serif
- **Scale**: 11px data, 13px body, 15px section headers, 18px panel titles

### Effects (Full Sci-Fi HUD)

- **Panel borders**: Double-line bezel (1px bright + 1px dark offset) — cockpit instrument feel
- **Corner brackets**: L-shaped corner brackets on panels via clip-path or pseudo-elements
- **Scan lines**: 5% opacity repeating gradient, animated slow vertical drift (30s cycle)
- **Glow**: Strong phosphor bloom — `0 0 12px rgba(0,255,136,0.5), 0 0 24px rgba(0,255,136,0.15)` + text-shadow on key readouts
- **HUD frame**: Entire viewport bordered with animated corner brackets and rotating tick marks
- **Parallax depth**: Outer panels angled 1-2deg toward center (cockpit wraparound)
- **Data cascade**: Numbers roll/cascade to final values on load (slot-machine animation)
- **Hexagonal grid**: Faint hex grid overlay on map, updates with zoom
- **Mil-spec grid**: Visible coordinate grid on map with edge markers
- **Threat rings**: Obstruction zones on sky plot pulse red with sawtooth edges
- **Satellite trails**: Sky plot shows predicted 15-minute arcs for each satellite
- **Boot sequence**: Panels "power on" sequentially with flicker animation (150ms), status bar items light up left-to-right
- **Glitch effects**: On errors, panels get CRT glitch (horizontal displacement + color channel split, 200ms)
- **Signal lost**: Full-screen scanline rain + "SIGNAL LOST" stencil overlay on connection loss
- **Audio cues** (Electron only): Click on target placement, sweep tone on scan completion
- **Radar sweep**: Sky plot has rotating sweep line animation
- **Pulsing markers**: Target marker and active waypoints pulse

---

## 4. Mission Planning Feature

### User Flow

1. User switches to MISSION tab in command sidebar
2. Origin defaults to GPS/current location (editable)
3. User enters destination address (autocomplete via Nominatim)
4. "COMPUTE ROUTE" triggers route planning
5. Backend fetches route from OSRM, samples visibility along it, finds parking
6. Map renders color-coded route with waypoint markers
7. Waypoint list populates in sidebar; mission brief appears in intel panel
8. Click any waypoint for full analysis in intel panel

### Waypoint Card Format

```
WP-01  ★ Rest Area I-70 Mile 156
 ├ Coverage: 87% (15/18 sats)
 ├ Best window: 14:30-16:45 UTC
 ├ Status: CLEAR ●
 ├ Distance: 47.2 mi from origin
 ├ ETA: ~0h 52m
 ├ Next stop: 31.8 mi → WP-02
 ├ Amenities: [P] [WC] [F]
 └ Obstruction: Low (12° max horizon)
```

- ★ = Known parking (rest area, parking lot, gas station)
- ◆ = Pullover opportunity (good visibility, road shoulder/wide spot)
- Known parking areas ranked higher than pullover spots

### Mission Brief (Intel Panel)

```
MISSION BRIEF
─────────────────────────────────
ROUTE: Denver, CO → Moab, UT
DISTANCE: 352.4 mi
DRIVE TIME: ~5h 18m
STOPS FOUND: 7 recommended
MAX GAP: 62 mi (WP-03→WP-04)
DEAD ZONES: 2 segments (18 mi)
COVERAGE: 84% of route

SIGNAL FORECAST
▓▓▓▓▓▓░░▓▓▓▓▓▓▓░▓▓▓▓▓▓▓▓▓▓▓
↑ Denver        Gap    Moab ↑
```

### Map Rendering

- Route polyline: 4px thick, color gradient by segment visibility (green/amber/red)
- Known parking: Filled star markers with designation codes (WP-01, WP-02...)
- Pullover opportunities: Diamond markers
- Dead zones: Animated dashed red line + "NO SIGNAL" label
- Clickable segments show popup with local stats

### Amenity Data

Pulled from OSM tags along the route:
- `amenity=parking` / `amenity=rest_area` — parking
- `amenity=toilets` — restrooms
- `amenity=fuel` — gas stations
- `amenity=restaurant` / `amenity=fast_food` — food
- Displayed as icon badges: [P] [WC] [F] [food]

---

## 5. Backend Changes

### New Endpoints

**POST `/api/v1/route/plan`** — Mission route planning
- Input: `{ origin: {lat, lon} | address, destination: {lat, lon} | address, sample_interval_m: 500, time_utc: "ISO8601" }`
- Process:
  1. Geocode addresses if needed (Nominatim)
  2. Fetch route from OSRM
  3. Sample points along route polyline at `sample_interval_m`
  4. Run visibility analysis at each sample (buildings + terrain + satellites)
  5. Query OSM Overpass for amenities within 500m of route
  6. Score and rank potential stops (visibility * parking_preference * spacing)
  7. Identify dead zone segments
- Response: `{ route_geojson, waypoints[], mission_summary, dead_zones[], data_quality }`
- Cache: Route hash → Redis, 5min TTL

**POST `/api/v1/route/waypoint`** — Detailed waypoint analysis
- Input: `{ lat, lon, time_utc }`
- Response: Full satellite analysis + amenity data + optimal time windows (next 24h)

### Modified Endpoints

**POST `/api/v1/analyze`** — Add data quality field
```json
{
  "...existing fields...",
  "data_quality": {
    "buildings": "full" | "partial" | "none",
    "terrain": "full" | "none",
    "satellites": "live" | "cached" | "stale",
    "sources": ["overture", "osm", "postgis"],
    "warnings": ["No building data — obstruction analysis may be inaccurate"]
  }
}
```

**POST `/api/v1/heatmap`** — Same `data_quality` addition

### Backend Fixes

1. **Wire terrain**: Connect `CopernicusTerrainClient` to `_DataPipelineAdapter.fetch_terrain()` instead of returning `[]`
2. **Fix constellations**: `get_constellations()` should derive name/operator from TLE data, not hardcode "Starlink"/"SpaceX"
3. **Remove dead code**: Delete `grid_analyzer.py`, remove unused `ObstructionEngine` class from `ray_casting_engine.py`
4. **Fix silent failures**: When `get_buildings_in_radius()` returns empty GeoDataFrame, set `data_quality.buildings = "none"` and populate warnings
5. **Add OSRM client**: New module `backend/osrm_client.py` for route fetching and polyline sampling
6. **Add amenity client**: New module or extension to `data_pipeline.py` for OSM amenity queries

### Data Quality Indicators

| Indicator | Green | Amber | Red |
|-----------|-------|-------|-----|
| Buildings | Full Overture/PostGIS data | OSM fallback only | No data (empty) |
| Terrain | Copernicus loaded | — | Unavailable |
| Satellites | Live TLE (<4h) | Cached (4-24h) | Stale (>24h) |
| Routing | OSRM responded | — | OSRM unavailable |

Frontend renders these as illuminated status LEDs in the status bar. Amber/red triggers persistent warning banner in intel panel.

---

## 6. Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Routing engine | OSRM (public demo or self-hosted Docker) | Free, OSM data, self-hostable, no API key |
| Parking/amenity data | OSM Overpass API | Already in stack, has rest_area/parking tags |
| Map tiles | CartoDB dark_matter | Matches tactical dark aesthetic |
| Icons | Lucide Icons (line style) | Clean, comprehensive, MIT license |
| Monospace font | JetBrains Mono | Free, excellent readability |
| UI font | Inter | System-compatible, clean |
| Effects | Pure CSS (gradients, animations, clip-path) | No extra deps, GPU-accelerated |
| Sky plot | HTML5 Canvas (existing, restyled) | Already built |
| Route rendering | Leaflet Polyline with color-coded segments | Native Leaflet, no extra plugin needed |
| Terminal input | Custom input with command parsing | Lightweight, no deps |

---

## 7. Frontend Component Map

| Component | File | Responsibility |
|-----------|------|----------------|
| App shell & layout | `js/app.js` | Panel management, tab switching, boot sequence |
| Command sidebar | `js/command-panel.js` (new) | Search, params, mission planning UI |
| Intel panel | `js/intel-panel.js` (new) | Sky plot, satellite list, mission brief |
| Status bar | `js/status-bar.js` (new) | Health indicators, clock, data quality LEDs |
| Timeline | `js/timeline.js` (new) | 24hr scrubber with radar sweep styling |
| Sky plot | `js/sky-plot.js` (existing, restyled) | Polar plot with threat rings, satellite trails |
| Route renderer | `js/route-renderer.js` (new) | Color-coded route polyline, waypoint markers |
| API client | `js/api-client.js` (existing, extended) | Add route/plan and route/waypoint calls |
| Effects engine | `js/effects.js` (new) | Boot sequence, glitch, data cascade animations |
| HUD overlay | `js/hud-overlay.js` (new) | Corner brackets, hex grid, targeting reticle |

---

## 8. Out of Scope (YAGNI)

- Multi-user / authentication
- Real-time satellite tracking (live updating positions)
- Route optimization (reordering waypoints)
- Offline map tiles
- Mobile native app (Electron desktop only + web)
- Fuel cost estimation
- Weather integration
- Multi-constellation comparison (Starlink only for now)
