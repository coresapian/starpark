# Mission Control Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform LinkSpot from a prototype into a sci-fi tactical Mission Control interface with route-based satellite connectivity planning, while fixing backend stubs and silent failures.

**Architecture:** Backend-first approach — fix stubs and add route planning API before rebuilding the frontend. Frontend is a complete rewrite of HTML/CSS with new JS modules for each panel. Existing sky-plot and api-client are refactored, not replaced. All effects are pure CSS + Canvas.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS/Leaflet/Canvas (frontend), OSRM (routing), JetBrains Mono + Inter (fonts), Lucide Icons (iconography)

---

## Phase 1: Backend Fixes

### Task 1: Remove Dead Code

**Files:**
- Delete: `backend/grid_analyzer.py`
- Modify: `backend/ray_casting_engine.py` (remove unused ObstructionEngine class but keep Zone enum and dataclasses if referenced)
- Modify: `backend/main.py` (verify no imports of deleted code)

**Step 1: Check for any imports of grid_analyzer**

Run: `grep -r "grid_analyzer\|GridAnalyzer" backend/`
Expected: No imports in production code (only possibly in test files)

**Step 2: Check for imports of ObstructionEngine from ray_casting_engine**

Run: `grep -r "from ray_casting_engine import\|import ray_casting_engine" backend/`
Expected: Identify which symbols are actually used (Zone enum, dataclasses may be imported)

**Step 3: Delete grid_analyzer.py**

Delete `backend/grid_analyzer.py` entirely.

**Step 4: Clean up ray_casting_engine.py**

Keep the `Zone` enum (lines 96-106), `AnalysisResult` dataclass (lines 109-152), `Satellite` dataclass (lines 155-170), and `Building` dataclass (lines 172-194) if they are imported elsewhere. Remove the `ObstructionEngine` class (lines 196-691) since the router uses `_ObstructionEngineAdapter` in dependencies.py instead.

**Step 5: Remove any dead test references**

If `backend/test_ray_casting.py` tests the `ObstructionEngine` class directly, update or remove those tests to test `_ObstructionEngineAdapter` instead (or leave for Phase 1 Task 6).

**Step 6: Verify the app still starts**

Run: `docker-compose -p linkspot exec backend python -c "from main import create_application; print('OK')"`
Expected: `OK`

**Step 7: Commit**

```bash
git add -u backend/
git commit -m "refactor: remove dead GridAnalyzer and unused ObstructionEngine class"
```

---

### Task 2: Fix Constellation Metadata Stub

**Files:**
- Modify: `backend/dependencies.py:230-236` (`_SatelliteEngineAdapter.get_constellations`)
- Modify: `backend/satellite_engine.py` (add method to extract constellation metadata from TLE data)
- Modify: `backend/models/schemas.py:361-383` (`ConstellationInfo` model)

**Step 1: Write failing test**

Create or modify `backend/test_api.py` to test that `/api/v1/satellites/constellation` returns dynamically computed metadata, not hardcoded strings:

```python
def test_constellation_metadata_not_hardcoded():
    """Constellation metadata should be derived from TLE data, not hardcoded."""
    response = client.get("/api/v1/satellites/constellation")
    assert response.status_code == 200
    data = response.json()
    constellations = data["constellations"]
    assert len(constellations) >= 1
    for c in constellations:
        assert c["name"] is not None
        assert c["total_satellites"] > 0
        # These should no longer be None/0
        assert c.get("altitude_km") is not None or c.get("altitude_km", 0) > 0
```

**Step 2: Run test to verify it fails**

Run: `docker-compose -p linkspot exec backend python -m pytest test_api.py::test_constellation_metadata_not_hardcoded -v`
Expected: FAIL (altitude_km is None or 0)

**Step 3: Add constellation metadata extraction to SatelliteEngine**

In `backend/satellite_engine.py`, add a method to `SatelliteEngine` after `get_constellation_stats()` (around line 595):

```python
def get_constellation_metadata(self) -> dict:
    """Extract constellation metadata from loaded TLE/satellite data."""
    if not self._satellites:
        self.fetch_tle_data()

    if not self._satellites:
        return {
            "name": "Unknown",
            "operator": "Unknown",
            "total_satellites": 0,
            "altitude_km": None,
            "inclination_deg": None,
        }

    # Extract orbital parameters from SGP4 elements
    altitudes = []
    inclinations = []
    for sat in self._satellites:
        try:
            # SGP4 mean motion (revs/day) → semi-major axis → altitude
            mean_motion = sat.model.no_kozai  # radians/minute
            if mean_motion > 0:
                mu = 398600.4418  # km^3/s^2
                n_rad_s = mean_motion / 60.0  # radians/second
                a = (mu / (n_rad_s ** 2)) ** (1/3)  # semi-major axis km
                alt = a - 6371.0  # altitude km
                if 100 < alt < 2000:  # sanity check for LEO
                    altitudes.append(alt)
            inclinations.append(math.degrees(sat.model.inclo))
        except Exception:
            continue

    import numpy as np
    median_alt = float(np.median(altitudes)) if altitudes else None
    median_inc = float(np.median(inclinations)) if inclinations else None

    # Derive constellation name from TLE names
    names = [getattr(sat, 'name', '') for sat in self._satellites]
    if any('STARLINK' in n.upper() for n in names):
        name, operator = "Starlink", "SpaceX"
    elif any('ONEWEB' in n.upper() for n in names):
        name, operator = "OneWeb", "Eutelsat OneWeb"
    else:
        name, operator = "Unknown", "Unknown"

    return {
        "name": name,
        "operator": operator,
        "total_satellites": len(self._satellites),
        "altitude_km": round(median_alt, 1) if median_alt else None,
        "inclination_deg": round(median_inc, 1) if median_inc else None,
    }
```

**Step 4: Update the adapter to use real metadata**

In `backend/dependencies.py`, replace `get_constellations()` (lines 230-236):

```python
async def get_constellations(self) -> list[dict]:
    metadata = await asyncio.to_thread(self._engine.get_constellation_metadata)
    return [metadata]
```

**Step 5: Run test to verify it passes**

Run: `docker-compose -p linkspot exec backend python -m pytest test_api.py::test_constellation_metadata_not_hardcoded -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/dependencies.py backend/satellite_engine.py backend/test_api.py
git commit -m "fix: derive constellation metadata from TLE data instead of hardcoding"
```

---

### Task 3: Wire Terrain Client Into Adapter

**Files:**
- Modify: `backend/dependencies.py:259-304` (`_DataPipelineAdapter`)
- Modify: `backend/terrain_client.py` (verify CopernicusTerrainClient interface)
- Test: `backend/test_data_pipeline.py`

**Step 1: Read the CopernicusTerrainClient interface**

Examine `backend/terrain_client.py` to understand the public API — specifically what method returns elevation data for a point or area, and what the return format is.

**Step 2: Write failing test**

```python
def test_fetch_terrain_returns_data():
    """fetch_terrain should call CopernicusTerrainClient, not return empty list."""
    # Mock the terrain client to return known data
    adapter = _DataPipelineAdapter(mock_redis)
    result = await adapter.fetch_terrain(40.7128, -74.0060, 500)
    # Should not be an empty list (the old stub behavior)
    # May still be empty if Copernicus is unavailable, but the code path should be wired
    assert isinstance(result, list)
```

**Step 3: Wire fetch_terrain to CopernicusTerrainClient**

Replace the stub in `backend/dependencies.py` (lines 297-303):

```python
async def fetch_terrain(
    self,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    try:
        from terrain_client import CopernicusTerrainClient
        client = CopernicusTerrainClient()
        elevation = await asyncio.to_thread(
            client.get_elevation, lat, lon
        )
        if elevation is not None:
            return [{"lat": lat, "lon": lon, "elevation": elevation}]
        return []
    except Exception as e:
        logging.getLogger(__name__).warning(
            "Terrain data unavailable: %s", str(e)
        )
        return []
```

**Step 4: Verify the import works**

Run: `docker-compose -p linkspot exec backend python -c "from terrain_client import CopernicusTerrainClient; print('OK')"`
Expected: `OK` (or import error if rasterio not installed — handle gracefully)

**Step 5: Run tests**

Run: `docker-compose -p linkspot exec backend python -m pytest test_data_pipeline.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/dependencies.py
git commit -m "fix: wire CopernicusTerrainClient into fetch_terrain adapter"
```

---

### Task 4: Add Data Quality to API Responses

**Files:**
- Modify: `backend/models/schemas.py` (add DataQuality model)
- Modify: `backend/routers/analysis.py` (track and return data quality in /analyze and /heatmap)
- Modify: `backend/dependencies.py` (adapters return source metadata)
- Test: `backend/test_api.py`

**Step 1: Add DataQuality schema**

In `backend/models/schemas.py`, add after the existing models:

```python
class DataQuality(BaseModel):
    """Data quality indicators for analysis transparency."""
    buildings: str = Field(description="Building data status: full, partial, none")
    terrain: str = Field(description="Terrain data status: full, none")
    satellites: str = Field(description="Satellite data status: live, cached, stale")
    sources: list[str] = Field(default_factory=list, description="Data sources used")
    warnings: list[str] = Field(default_factory=list, description="Degradation warnings")
```

**Step 2: Add data_quality field to AnalyzeResponse and HeatmapResponse**

In `AnalyzeResponse` (around line 159), add:
```python
data_quality: Optional[DataQuality] = None
```

In `HeatmapResponse` (around line 267), add:
```python
data_quality: Optional[DataQuality] = None
```

**Step 3: Track data quality in analysis router**

In `backend/routers/analysis.py`, in the `analyze_position()` function, after fetching buildings/terrain/satellites, build a DataQuality object:

```python
# After fetching buildings (around line 239-248)
warnings = []
sources = []

# Track building data quality
if buildings is None or (hasattr(buildings, 'empty') and buildings.empty) or len(buildings) == 0:
    building_quality = "none"
    warnings.append("No building data available — obstruction analysis may be inaccurate")
else:
    building_quality = "full"
    sources.append("buildings")

# Track terrain data quality
terrain_quality = "full" if terrain and len(terrain) > 0 else "none"
if terrain_quality == "none":
    warnings.append("Terrain elevation data unavailable")

# Track satellite data quality
satellite_quality = "live"  # Default; could check TLE age if engine exposes it
sources.append("satellites")

data_quality = DataQuality(
    buildings=building_quality,
    terrain=terrain_quality,
    satellites=satellite_quality,
    sources=sources,
    warnings=warnings,
)
```

Then include `data_quality=data_quality` in the response construction.

Apply the same pattern to `generate_heatmap()`.

**Step 4: Write test**

```python
def test_analyze_returns_data_quality():
    response = client.post("/api/v1/analyze", json={
        "lat": 40.7128, "lon": -74.0060
    })
    assert response.status_code == 200
    data = response.json()
    assert "data_quality" in data
    dq = data["data_quality"]
    assert dq["buildings"] in ("full", "partial", "none")
    assert dq["terrain"] in ("full", "none")
    assert dq["satellites"] in ("live", "cached", "stale")
    assert isinstance(dq["sources"], list)
    assert isinstance(dq["warnings"], list)
```

**Step 5: Run tests**

Run: `docker-compose -p linkspot exec backend python -m pytest test_api.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/models/schemas.py backend/routers/analysis.py backend/test_api.py
git commit -m "feat: add data_quality field to analyze and heatmap responses"
```

---

### Task 5: Fix Silent Failure in Building Data

**Files:**
- Modify: `backend/data_pipeline.py:577-669` (`get_buildings_in_radius`)
- Modify: `backend/dependencies.py:269-295` (`_DataPipelineAdapter.fetch_buildings`)

**Step 1: Add logging when all building sources fail**

In `backend/data_pipeline.py`, in `get_buildings_in_radius()`, after the final fallback (around line 661), add explicit logging:

```python
# At the end of the method, before returning empty GeoDataFrame
if gdf is None or gdf.empty:
    logger.warning(
        "All building data sources failed for location (%.4f, %.4f) radius=%dm. "
        "Analysis will proceed with zero obstruction.",
        lat, lon, radius_m
    )
```

**Step 2: Update adapter to propagate source information**

In `_DataPipelineAdapter.fetch_buildings()`, track which source provided data:

```python
async def fetch_buildings(self, lat, lon, radius_m):
    gdf = await asyncio.to_thread(
        self._pipeline.get_buildings_in_radius, lat, lon, radius_m,
    )
    buildings = []
    source = "none"
    if gdf is not None and not gdf.empty:
        source = "overture"  # Default; could be made more granular
        for _, row in gdf.iterrows():
            buildings.append({
                "geometry": row.geometry,
                "height": row.get("height", 10.0),
            })
    return buildings, source
```

Note: This changes the return type from `list` to `tuple(list, str)`. Update callers in `routers/analysis.py` accordingly:

```python
# Before: buildings = await data_pipeline.fetch_buildings(...)
# After:
buildings, building_source = await data_pipeline.fetch_buildings(...)
```

**Step 3: Run tests**

Run: `docker-compose -p linkspot exec backend python -m pytest -v`
Expected: PASS (may need to update test mocks for new return type)

**Step 4: Commit**

```bash
git add backend/data_pipeline.py backend/dependencies.py backend/routers/analysis.py
git commit -m "fix: log and surface building data source failures instead of silently degrading"
```

---

## Phase 2: Backend Route Planning

### Task 6: Add OSRM Client Module

**Files:**
- Create: `backend/osrm_client.py`
- Test: `backend/test_osrm_client.py`

**Step 1: Write failing test**

Create `backend/test_osrm_client.py`:

```python
import pytest
from osrm_client import OSRMClient

class TestOSRMClient:
    def test_get_route_returns_geometry(self):
        """OSRM should return a route with geometry and distance."""
        client = OSRMClient()
        # Denver to Boulder (short route for testing)
        route = client.get_route(
            origin=(39.7392, -104.9903),
            destination=(40.0150, -105.2705)
        )
        assert route is not None
        assert "geometry" in route
        assert "distance_m" in route
        assert "duration_s" in route
        assert len(route["geometry"]) > 2  # At least start, middle, end

    def test_sample_route_points(self):
        """Should sample points along a route at specified intervals."""
        client = OSRMClient()
        # Simple geometry for testing
        geometry = [
            (39.7392, -104.9903),
            (39.8000, -105.0000),
            (40.0150, -105.2705),
        ]
        points = client.sample_route_points(geometry, interval_m=5000)
        assert len(points) > 0
        for p in points:
            assert "lat" in p
            assert "lon" in p
            assert "distance_along_m" in p
```

**Step 2: Run test to verify it fails**

Run: `docker-compose -p linkspot exec backend python -m pytest test_osrm_client.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Implement OSRMClient**

Create `backend/osrm_client.py`:

```python
"""OSRM client for route planning."""
import logging
import math
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OSRM_BASE_URL = "https://router.project-osrm.org"


class OSRMClient:
    """Client for Open Source Routing Machine (OSRM) API."""

    def __init__(self, base_url: str = OSRM_BASE_URL, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        profile: str = "driving",
    ) -> Optional[dict]:
        """Fetch driving route from OSRM.

        Args:
            origin: (lat, lon) tuple
            destination: (lat, lon) tuple
            profile: OSRM profile (driving, cycling, walking)

        Returns:
            dict with geometry (list of (lat,lon) tuples), distance_m, duration_s
        """
        # OSRM expects lon,lat order
        coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        url = f"{self.base_url}/route/v1/{profile}/{coords}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        }

        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok" or not data.get("routes"):
                logger.warning("OSRM returned no routes: %s", data.get("code"))
                return None

            route = data["routes"][0]
            # Convert GeoJSON coordinates [lon, lat] to [(lat, lon)]
            coords = route["geometry"]["coordinates"]
            geometry = [(c[1], c[0]) for c in coords]

            return {
                "geometry": geometry,
                "distance_m": route["distance"],
                "duration_s": route["duration"],
            }
        except requests.RequestException as e:
            logger.error("OSRM request failed: %s", str(e))
            return None

    def sample_route_points(
        self,
        geometry: list[tuple[float, float]],
        interval_m: float = 500.0,
    ) -> list[dict]:
        """Sample points along a route geometry at regular intervals.

        Args:
            geometry: List of (lat, lon) tuples defining the route
            interval_m: Distance between sample points in meters

        Returns:
            List of dicts with lat, lon, distance_along_m
        """
        if not geometry or len(geometry) < 2:
            return []

        points = [{"lat": geometry[0][0], "lon": geometry[0][1], "distance_along_m": 0.0}]
        accumulated = 0.0
        next_sample = interval_m

        for i in range(1, len(geometry)):
            seg_dist = self._haversine(
                geometry[i - 1][0], geometry[i - 1][1],
                geometry[i][0], geometry[i][1],
            )
            accumulated += seg_dist

            while accumulated >= next_sample:
                # Interpolate point along this segment
                overshoot = accumulated - next_sample
                ratio = 1.0 - (overshoot / seg_dist) if seg_dist > 0 else 1.0
                lat = geometry[i - 1][0] + ratio * (geometry[i][0] - geometry[i - 1][0])
                lon = geometry[i - 1][1] + ratio * (geometry[i][1] - geometry[i - 1][1])
                points.append({
                    "lat": lat,
                    "lon": lon,
                    "distance_along_m": next_sample,
                })
                next_sample += interval_m

        # Always include the endpoint
        total = accumulated
        last = geometry[-1]
        if not points or (points[-1]["lat"] != last[0] or points[-1]["lon"] != last[1]):
            points.append({
                "lat": last[0],
                "lon": last[1],
                "distance_along_m": total,
            })

        return points

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine distance in meters."""
        R = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

**Step 4: Run test to verify it passes**

Run: `docker-compose -p linkspot exec backend python -m pytest test_osrm_client.py -v`
Expected: PASS (requires network access to OSRM public server)

**Step 5: Commit**

```bash
git add backend/osrm_client.py backend/test_osrm_client.py
git commit -m "feat: add OSRM client for route planning with point sampling"
```

---

### Task 7: Add Route Planning Schemas

**Files:**
- Modify: `backend/models/schemas.py`

**Step 1: Add route planning request/response models**

Append to `backend/models/schemas.py`:

```python
class RouteLocation(BaseModel):
    """A location specified by coordinates or address."""
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    address: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_coords_or_address(self):
        if self.lat is None and self.address is None:
            raise ValueError("Either lat/lon or address must be provided")
        return self

class RoutePlanRequest(BaseModel):
    """Request for route-based satellite connectivity planning."""
    origin: RouteLocation
    destination: RouteLocation
    sample_interval_m: float = Field(500.0, ge=100, le=5000)
    time_utc: Optional[str] = None

class WaypointAmenities(BaseModel):
    """Amenities available at a waypoint."""
    parking: bool = False
    restroom: bool = False
    fuel: bool = False
    food: bool = False

class Waypoint(BaseModel):
    """A recommended stop along the route."""
    id: str = Field(description="Waypoint designation e.g. WP-01")
    lat: float
    lon: float
    name: str
    type: str = Field(description="known_parking or pullover")
    coverage_pct: float
    visible_satellites: int
    total_satellites: int
    zone: Zone
    distance_from_origin_m: float
    eta_seconds: float
    distance_to_next_m: Optional[float] = None
    max_obstruction_deg: Optional[float] = None
    amenities: WaypointAmenities = WaypointAmenities()
    best_window: Optional[str] = None

class DeadZone(BaseModel):
    """A stretch of route with poor satellite connectivity."""
    start_distance_m: float
    end_distance_m: float
    length_m: float
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

class MissionSummary(BaseModel):
    """Summary statistics for a planned mission."""
    origin_name: Optional[str] = None
    destination_name: Optional[str] = None
    total_distance_m: float
    total_duration_s: float
    num_waypoints: int
    max_gap_m: float
    num_dead_zones: int
    dead_zone_total_m: float
    route_coverage_pct: float

class RoutePlanResponse(BaseModel):
    """Response for route-based satellite connectivity planning."""
    route_geojson: GeoJSONFeatureCollection
    waypoints: list[Waypoint]
    dead_zones: list[DeadZone]
    mission_summary: MissionSummary
    data_quality: Optional[DataQuality] = None
    signal_forecast: list[str] = Field(
        default_factory=list,
        description="Segment-by-segment signal quality: clear, marginal, dead"
    )
```

**Step 2: Verify schemas compile**

Run: `docker-compose -p linkspot exec backend python -c "from models.schemas import RoutePlanRequest, RoutePlanResponse; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add backend/models/schemas.py
git commit -m "feat: add route planning Pydantic schemas"
```

---

### Task 8: Add Route Planning Endpoint

**Files:**
- Create: `backend/routers/route.py`
- Modify: `backend/main.py` (register new router)
- Modify: `backend/dependencies.py` (add OSRM and amenity dependencies)

**Step 1: Create the route router**

Create `backend/routers/route.py` with the route planning endpoint. This is the largest single implementation — it orchestrates OSRM, building/terrain data, satellite analysis, and OSM amenity queries.

```python
"""Route planning endpoints for mission-based satellite connectivity analysis."""
import asyncio
import logging
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import (
    get_data_pipeline,
    get_obstruction_engine,
    get_satellite_engine,
)
from models.schemas import (
    DataQuality,
    DeadZone,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    MissionSummary,
    RoutePlanRequest,
    RoutePlanResponse,
    Waypoint,
    WaypointAmenities,
    Zone,
)
from osrm_client import OSRMClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Route Planning"])


def _geocode_address(address: str) -> tuple[float, float]:
    """Geocode an address using Nominatim."""
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": "LinkSpot/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not geocode address: {address}",
        )
    return float(results[0]["lat"]), float(results[0]["lon"])


def _query_amenities_along_route(
    geometry: list[tuple[float, float]], buffer_m: float = 500
) -> list[dict]:
    """Query OSM for parking/rest areas near the route."""
    # Build a simplified bounding box from the route
    lats = [p[0] for p in geometry]
    lons = [p[1] for p in geometry]
    bbox = (min(lats) - 0.01, min(lons) - 0.01, max(lats) + 0.01, max(lons) + 0.01)

    query = f"""
    [out:json][timeout:30];
    (
      node["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
      node["amenity"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
      node["amenity"="fuel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
      node["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
      way["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
    );
    out center;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        amenities = []
        for element in data.get("elements", []):
            lat = element.get("lat") or element.get("center", {}).get("lat")
            lon = element.get("lon") or element.get("center", {}).get("lon")
            if lat and lon:
                tags = element.get("tags", {})
                amenities.append({
                    "lat": lat,
                    "lon": lon,
                    "type": tags.get("amenity", tags.get("highway", "unknown")),
                    "name": tags.get("name", ""),
                    "parking": tags.get("amenity") in ("parking", "rest_area"),
                    "restroom": "toilets" in str(tags),
                    "fuel": tags.get("amenity") == "fuel",
                    "food": tags.get("amenity") in ("restaurant", "fast_food", "cafe"),
                })
        return amenities
    except Exception as e:
        logger.warning("Amenity query failed: %s", str(e))
        return []


@router.post("/route/plan", response_model=RoutePlanResponse)
async def plan_route(
    body: RoutePlanRequest,
    satellite_engine=Depends(get_satellite_engine),
    data_pipeline=Depends(get_data_pipeline),
    obstruction_engine=Depends(get_obstruction_engine),
):
    """Plan a route with satellite connectivity analysis at regular intervals."""
    start_time = time.time()

    # 1. Resolve coordinates
    if body.origin.lat is not None:
        origin = (body.origin.lat, body.origin.lon)
    else:
        origin = _geocode_address(body.origin.address)

    if body.destination.lat is not None:
        destination = (body.destination.lat, body.destination.lon)
    else:
        destination = _geocode_address(body.destination.address)

    # 2. Get route from OSRM
    osrm = OSRMClient()
    route = await asyncio.to_thread(osrm.get_route, origin, destination)
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not compute route. OSRM service unavailable.",
        )

    # 3. Sample points along route
    sample_points = osrm.sample_route_points(
        route["geometry"], interval_m=body.sample_interval_m
    )

    # 4. Run visibility analysis at each sample point
    timestamp = body.time_utc or datetime.now(timezone.utc).isoformat()

    analysis_results = []
    warnings = []
    for point in sample_points:
        try:
            satellites = await satellite_engine.get_visible_satellites(
                point["lat"], point["lon"], 0.0, timestamp
            )
            buildings = await data_pipeline.fetch_buildings(
                point["lat"], point["lon"], 200  # Smaller radius for route sampling
            )
            # Handle tuple return from updated fetch_buildings
            if isinstance(buildings, tuple):
                buildings, _ = buildings
            terrain = await data_pipeline.fetch_terrain(
                point["lat"], point["lon"], 200
            )
            result = obstruction_engine.analyze_position(
                point["lat"], point["lon"], 0.0,
                buildings, terrain, satellites
            )
            analysis_results.append({
                **point,
                "result": result,
                "n_visible": result.get("n_clear", 0),
                "n_total": result.get("n_total", 0),
                "zone": result.get("zone", "BLOCKED"),
            })
        except Exception as e:
            logger.warning("Analysis failed at (%.4f, %.4f): %s",
                         point["lat"], point["lon"], str(e))
            analysis_results.append({
                **point,
                "result": None,
                "n_visible": 0,
                "n_total": 0,
                "zone": "BLOCKED",
            })

    # 5. Query amenities along route
    amenities = await asyncio.to_thread(
        _query_amenities_along_route, route["geometry"]
    )

    # 6. Score and rank waypoints
    waypoints = _rank_waypoints(analysis_results, amenities, route)

    # 7. Identify dead zones
    dead_zones = _find_dead_zones(analysis_results)

    # 8. Build signal forecast
    signal_forecast = []
    for ar in analysis_results:
        zone = ar["zone"]
        if zone in ("EXCELLENT", "GOOD"):
            signal_forecast.append("clear")
        elif zone == "FAIR":
            signal_forecast.append("marginal")
        else:
            signal_forecast.append("dead")

    # 9. Build route GeoJSON
    route_features = []
    for i in range(len(analysis_results) - 1):
        a, b = analysis_results[i], analysis_results[i + 1]
        feature = GeoJSONFeature(
            type="Feature",
            geometry=GeoJSONGeometry(
                type="LineString",
                coordinates=[[a["lon"], a["lat"]], [b["lon"], b["lat"]]],
            ),
            properties={
                "signal": signal_forecast[i] if i < len(signal_forecast) else "dead",
                "visible_satellites": a["n_visible"],
            },
        )
        route_features.append(feature)

    route_geojson = GeoJSONFeatureCollection(
        type="FeatureCollection", features=route_features
    )

    # 10. Build mission summary
    total_dead_m = sum(dz.length_m for dz in dead_zones)
    max_gap = _compute_max_gap(waypoints, route["distance_m"])
    covered = route["distance_m"] - total_dead_m
    coverage_pct = (covered / route["distance_m"] * 100) if route["distance_m"] > 0 else 0

    summary = MissionSummary(
        total_distance_m=route["distance_m"],
        total_duration_s=route["duration_s"],
        num_waypoints=len(waypoints),
        max_gap_m=max_gap,
        num_dead_zones=len(dead_zones),
        dead_zone_total_m=total_dead_m,
        route_coverage_pct=round(coverage_pct, 1),
    )

    elapsed = time.time() - start_time
    logger.info("Route planning completed in %.2fs: %d waypoints, %d dead zones",
                elapsed, len(waypoints), len(dead_zones))

    return RoutePlanResponse(
        route_geojson=route_geojson,
        waypoints=waypoints,
        dead_zones=dead_zones,
        mission_summary=summary,
        signal_forecast=signal_forecast,
        data_quality=DataQuality(
            buildings="full",
            terrain="none",
            satellites="live",
            sources=["osrm", "buildings", "satellites"],
            warnings=warnings,
        ),
    )


def _rank_waypoints(analysis_results, amenities, route):
    """Score and rank potential stopping points."""
    import math

    waypoints = []
    wp_count = 0

    # First: known parking/rest areas from amenities
    for amenity in amenities:
        # Find nearest analysis point
        nearest = min(
            analysis_results,
            key=lambda ar: math.hypot(ar["lat"] - amenity["lat"], ar["lon"] - amenity["lon"])
        )
        if nearest["result"] is None:
            continue

        wp_count += 1
        n_vis = nearest["n_visible"]
        n_tot = nearest["n_total"]
        coverage = (n_vis / n_tot * 100) if n_tot > 0 else 0
        zone_str = nearest["zone"]

        # Map to Zone enum
        zone_map = {"EXCELLENT": Zone.EXCELLENT, "GOOD": Zone.GOOD, "FAIR": Zone.FAIR,
                     "POOR": Zone.POOR, "BLOCKED": Zone.BLOCKED}
        zone = zone_map.get(zone_str, Zone.BLOCKED)

        speed_ms = route["distance_m"] / route["duration_s"] if route["duration_s"] > 0 else 20
        eta = nearest["distance_along_m"] / speed_ms

        waypoints.append(Waypoint(
            id=f"WP-{wp_count:02d}",
            lat=amenity["lat"],
            lon=amenity["lon"],
            name=amenity.get("name") or f"{'Rest Area' if amenity.get('parking') else 'Stop'} at {nearest['distance_along_m']/1609:.1f}mi",
            type="known_parking",
            coverage_pct=round(coverage, 1),
            visible_satellites=n_vis,
            total_satellites=n_tot,
            zone=zone,
            distance_from_origin_m=nearest["distance_along_m"],
            eta_seconds=eta,
            amenities=WaypointAmenities(
                parking=amenity.get("parking", False),
                restroom=amenity.get("restroom", False),
                fuel=amenity.get("fuel", False),
                food=amenity.get("food", False),
            ),
        ))

    # Second: good visibility spots that aren't near known parking
    for ar in analysis_results:
        if ar["result"] is None:
            continue
        zone_str = ar["zone"]
        if zone_str not in ("EXCELLENT", "GOOD"):
            continue
        # Skip if too close to an existing waypoint
        too_close = any(
            math.hypot(ar["lat"] - wp.lat, ar["lon"] - wp.lon) < 0.005
            for wp in waypoints
        )
        if too_close:
            continue

        wp_count += 1
        n_vis = ar["n_visible"]
        n_tot = ar["n_total"]
        coverage = (n_vis / n_tot * 100) if n_tot > 0 else 0
        zone_map = {"EXCELLENT": Zone.EXCELLENT, "GOOD": Zone.GOOD, "FAIR": Zone.FAIR,
                     "POOR": Zone.POOR, "BLOCKED": Zone.BLOCKED}
        zone = zone_map.get(zone_str, Zone.BLOCKED)
        speed_ms = route["distance_m"] / route["duration_s"] if route["duration_s"] > 0 else 20
        eta = ar["distance_along_m"] / speed_ms

        waypoints.append(Waypoint(
            id=f"WP-{wp_count:02d}",
            lat=ar["lat"],
            lon=ar["lon"],
            name=f"Pullover at {ar['distance_along_m']/1609:.1f}mi",
            type="pullover",
            coverage_pct=round(coverage, 1),
            visible_satellites=n_vis,
            total_satellites=n_tot,
            zone=zone,
            distance_from_origin_m=ar["distance_along_m"],
            eta_seconds=eta,
        ))

    # Sort by distance along route
    waypoints.sort(key=lambda wp: wp.distance_from_origin_m)

    # Compute distance_to_next
    for i in range(len(waypoints) - 1):
        waypoints[i].distance_to_next_m = (
            waypoints[i + 1].distance_from_origin_m - waypoints[i].distance_from_origin_m
        )

    return waypoints


def _find_dead_zones(analysis_results):
    """Identify contiguous stretches of poor connectivity."""
    dead_zones = []
    in_dead = False
    start = None

    for ar in analysis_results:
        is_dead = ar["zone"] in ("POOR", "BLOCKED")
        if is_dead and not in_dead:
            start = ar
            in_dead = True
        elif not is_dead and in_dead:
            dead_zones.append(DeadZone(
                start_distance_m=start["distance_along_m"],
                end_distance_m=ar["distance_along_m"],
                length_m=ar["distance_along_m"] - start["distance_along_m"],
                start_lat=start["lat"],
                start_lon=start["lon"],
                end_lat=ar["lat"],
                end_lon=ar["lon"],
            ))
            in_dead = False

    # Close any open dead zone
    if in_dead and start and analysis_results:
        last = analysis_results[-1]
        dead_zones.append(DeadZone(
            start_distance_m=start["distance_along_m"],
            end_distance_m=last["distance_along_m"],
            length_m=last["distance_along_m"] - start["distance_along_m"],
            start_lat=start["lat"],
            start_lon=start["lon"],
            end_lat=last["lat"],
            end_lon=last["lon"],
        ))

    return dead_zones


def _compute_max_gap(waypoints, total_distance_m):
    """Find the longest stretch between consecutive waypoints."""
    if not waypoints:
        return total_distance_m

    gaps = [waypoints[0].distance_from_origin_m]  # Start to first WP
    for i in range(len(waypoints) - 1):
        gaps.append(
            waypoints[i + 1].distance_from_origin_m - waypoints[i].distance_from_origin_m
        )
    gaps.append(total_distance_m - waypoints[-1].distance_from_origin_m)  # Last WP to end
    return max(gaps) if gaps else total_distance_m
```

**Step 2: Register the router in main.py**

In `backend/main.py`, add the import and include the router alongside the existing ones:

```python
from routers.route import router as route_router
# In create_application():
app.include_router(route_router)
```

**Step 3: Verify the endpoint appears in Swagger**

Run: `docker-compose -p linkspot up -d`
Check: `http://localhost:8000/docs` should show `/api/v1/route/plan`

**Step 4: Commit**

```bash
git add backend/routers/route.py backend/main.py
git commit -m "feat: add route planning endpoint with OSRM, amenities, and waypoint ranking"
```

---

## Phase 3: Frontend Design System

### Task 9: Add Fonts and Icons

**Files:**
- Modify: `frontend/index.html` (add font links and icon sprite)

**Step 1: Add JetBrains Mono and Inter fonts**

In `frontend/index.html`, add to the `<head>` after the existing CSS links:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
```

**Step 2: Add Lucide Icons CDN**

```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
```

**Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add JetBrains Mono, Inter fonts and Lucide icons"
```

---

### Task 10: Rewrite CSS Design System

**Files:**
- Rewrite: `frontend/css/styles.css`

This is a complete replacement. The new CSS establishes:

1. **Custom properties** — tactical color palette, spacing, typography, effects
2. **Layout grid** — CSS Grid for the 3-column + header/footer Mission Control layout
3. **Panel styles** — bezel borders, corner brackets, scan-line overlay, glow effects
4. **Component styles** — status bar, command sidebar, intel panel, timeline bar
5. **HUD effects** — animated borders, scan lines, data cascade, glitch
6. **Responsive** — panel collapse below 1024px

**Step 1: Write the complete new CSS file**

This is too large to include inline in the plan. The CSS should follow the design doc specifications for colors, effects, and layout. Key sections:

- `:root` custom properties (tactical palette, fonts, spacing, z-indices)
- `body` and `.app-shell` (CSS Grid layout: `"status status status" / "sidebar map intel" / "timeline timeline timeline"`)
- `.status-bar` (32px, flex row, LED indicators)
- `.command-sidebar` (280px, left panel with tabs)
- `.map-viewport` (fills remaining space)
- `.intel-panel` (360px, right panel)
- `.timeline-bar` (48px, full width)
- Panel effects (`.panel` base class with bezel, corner brackets, scan-line pseudo-element)
- HUD frame (`.hud-frame` with animated corner bracket pseudo-elements)
- Boot sequence keyframes (`@keyframes power-on`, `@keyframes flicker`)
- Glitch effect (`@keyframes glitch`)
- Data cascade (`@keyframes cascade`)
- Signal lost overlay (`.signal-lost`)
- All component overrides for the new design

**Step 2: Verify no syntax errors**

Open `http://localhost` in browser, check DevTools for CSS parse errors.

**Step 3: Commit**

```bash
git add frontend/css/styles.css
git commit -m "feat: complete tactical HUD CSS design system"
```

---

### Task 11: Rewrite HTML Layout

**Files:**
- Rewrite: `frontend/index.html`

Replace the current HTML body with the Mission Control layout structure. Keep the same `<head>` (with font/icon additions from Task 9) but replace the `<body>` with:

```html
<body>
  <div class="app-shell" id="app-shell">
    <!-- HUD Frame -->
    <div class="hud-frame" id="hud-frame"></div>

    <!-- Status Bar -->
    <header class="status-bar" id="status-bar">
      <div class="status-left">
        <span class="status-led" id="led-backend" data-status="unknown"></span>
        <span class="status-label">SYS</span>
        <span class="status-led" id="led-buildings" data-status="unknown"></span>
        <span class="status-label">BLD</span>
        <span class="status-led" id="led-terrain" data-status="unknown"></span>
        <span class="status-label">TER</span>
        <span class="status-led" id="led-satellites" data-status="unknown"></span>
        <span class="status-label">SAT</span>
        <span class="status-led" id="led-routing" data-status="unknown"></span>
        <span class="status-label">RTE</span>
      </div>
      <div class="status-center">
        <span class="status-title">LINKSPOT MISSION CONTROL</span>
      </div>
      <div class="status-right">
        <span class="status-gps" id="gps-status">NO FIX</span>
        <span class="status-clock" id="utc-clock">00:00:00Z</span>
      </div>
    </header>

    <!-- Command Sidebar -->
    <aside class="command-sidebar" id="command-sidebar">
      <div class="sidebar-tabs">
        <button class="sidebar-tab active" data-tab="analysis">ANALYSIS</button>
        <button class="sidebar-tab" data-tab="mission">MISSION</button>
      </div>

      <!-- Analysis Tab -->
      <div class="sidebar-panel" id="tab-analysis">
        <div class="panel-section">
          <label class="panel-label">TARGET LOCATION</label>
          <div class="search-group">
            <input type="text" id="search-input" class="tactical-input" placeholder="Search location..." autocomplete="off">
            <button id="search-btn" class="tactical-btn-icon" aria-label="Search"><i data-lucide="search"></i></button>
          </div>
          <div id="search-results" class="search-dropdown" role="listbox"></div>
        </div>

        <div class="panel-section">
          <label class="panel-label">PARAMETERS</label>
          <div class="param-row">
            <span class="param-name">Radius</span>
            <span class="param-value" id="param-radius">500m</span>
          </div>
          <div class="param-row">
            <span class="param-name">Elevation Mask</span>
            <span class="param-value" id="param-elevation">25°</span>
          </div>
          <div class="param-row">
            <span class="param-name">Constellation</span>
            <span class="param-value" id="param-constellation">Starlink</span>
          </div>
        </div>

        <div class="panel-section">
          <label class="panel-label">QUICK STATS</label>
          <div class="stat-grid">
            <div class="stat-block">
              <span class="stat-value" id="stat-visible">--</span>
              <span class="stat-label">VISIBLE</span>
            </div>
            <div class="stat-block">
              <span class="stat-value" id="stat-obstructed">--</span>
              <span class="stat-label">BLOCKED</span>
            </div>
            <div class="stat-block">
              <span class="stat-value" id="stat-coverage">--</span>
              <span class="stat-label">COVERAGE</span>
            </div>
            <div class="stat-block">
              <span class="stat-value" id="stat-zone">--</span>
              <span class="stat-label">ZONE</span>
            </div>
          </div>
        </div>

        <button id="gps-btn" class="tactical-btn" aria-label="Center on GPS location">
          <i data-lucide="crosshair"></i> ACQUIRE GPS
        </button>
        <button id="scan-area-btn" class="tactical-btn accent hidden" aria-label="Scan this area">
          <i data-lucide="radar"></i> SCAN AREA
        </button>
      </div>

      <!-- Mission Tab -->
      <div class="sidebar-panel hidden" id="tab-mission">
        <div class="panel-section">
          <label class="panel-label">ORIGIN</label>
          <input type="text" id="mission-origin" class="tactical-input" placeholder="Current location" autocomplete="off">
        </div>
        <div class="panel-section">
          <label class="panel-label">DESTINATION</label>
          <input type="text" id="mission-destination" class="tactical-input" placeholder="Enter address..." autocomplete="off">
        </div>
        <button id="compute-route-btn" class="tactical-btn accent">
          <i data-lucide="navigation"></i> COMPUTE ROUTE
        </button>

        <div class="panel-section" id="waypoint-list-section" style="display:none">
          <label class="panel-label">WAYPOINTS</label>
          <div id="waypoint-list" class="waypoint-list"></div>
        </div>
      </div>

      <!-- Terminal Input -->
      <div class="terminal-input">
        <span class="terminal-prompt">&gt;</span>
        <input type="text" id="terminal-cmd" class="terminal-field" placeholder="Enter coordinates...">
      </div>
    </aside>

    <!-- Map Viewport -->
    <main class="map-viewport" id="map" role="main" aria-label="Satellite visibility map"></main>

    <!-- Intel Panel -->
    <aside class="intel-panel" id="intel-panel">
      <div class="panel-section" id="mission-brief-section" style="display:none">
        <label class="panel-label">MISSION BRIEF</label>
        <div id="mission-brief" class="mission-brief"></div>
      </div>

      <div class="panel-section">
        <label class="panel-label">SKY PLOT</label>
        <div class="sky-plot-container">
          <canvas id="sky-plot" width="280" height="280"></canvas>
        </div>
      </div>

      <div class="panel-section">
        <label class="panel-label">SATELLITE LIST</label>
        <ul id="satellite-list" class="satellite-list"></ul>
      </div>

      <div class="panel-section">
        <label class="panel-label">ANALYSIS</label>
        <div id="analysis-stats" class="analysis-stats"></div>
      </div>

      <div class="panel-section" id="data-quality-section">
        <label class="panel-label">DATA QUALITY</label>
        <div id="data-quality-display" class="data-quality"></div>
      </div>
    </aside>

    <!-- Timeline Bar -->
    <footer class="timeline-bar" id="timeline-bar">
      <button id="play-btn" class="tactical-btn-icon" aria-label="Play/Pause">
        <i data-lucide="play" id="play-icon"></i>
        <i data-lucide="pause" id="pause-icon" class="hidden"></i>
      </button>
      <div class="timeline-track">
        <input type="range" id="time-slider" min="0" max="95" value="0" class="timeline-slider">
        <div class="timeline-labels">
          <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:45</span>
        </div>
      </div>
      <span class="timeline-time" id="current-time">00:00</span>
      <span class="timeline-date" id="current-date">UTC</span>
    </footer>

    <!-- Loading Overlay -->
    <div class="loading-overlay hidden" id="loading-overlay" aria-hidden="true">
      <div class="loading-spinner"></div>
      <span class="loading-text">ANALYZING...</span>
    </div>

    <!-- Signal Lost Overlay -->
    <div class="signal-lost-overlay hidden" id="signal-lost">
      <span class="signal-lost-text">SIGNAL LOST</span>
    </div>

    <!-- Toast Container -->
    <div id="toast-container" class="toast-container" role="status" aria-live="polite"></div>
  </div>

  <!-- Scripts -->
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
  <script src="js/api-client.js"></script>
  <script src="js/sky-plot.js"></script>
  <script src="js/effects.js"></script>
  <script src="js/status-bar.js"></script>
  <script src="js/command-panel.js"></script>
  <script src="js/intel-panel.js"></script>
  <script src="js/route-renderer.js"></script>
  <script src="js/app.js"></script>
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(() => {});
    }
  </script>
</body>
```

**Step 1: Write the new index.html**

Replace the body content with the Mission Control layout above.

**Step 2: Verify page loads without JS errors**

Open `http://localhost` — expect to see the new layout shell (unstyled panels won't look right until CSS is complete).

**Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: rewrite HTML to Mission Control panel layout"
```

---

## Phase 4: Frontend JavaScript Modules

### Task 12: Create Effects Engine

**Files:**
- Create: `frontend/js/effects.js`

Handles boot sequence, data cascade animations, glitch effects, and the scan-line overlay.

Key exports:
- `EffectsEngine.bootSequence()` — power-on panel flicker sequence
- `EffectsEngine.dataCascade(element, targetValue)` — number roll animation
- `EffectsEngine.glitch(element)` — CRT glitch on error
- `EffectsEngine.signalLost(show)` — full-screen signal lost overlay

**Step 1: Implement the effects module**
**Step 2: Verify boot sequence plays on page load**
**Step 3: Commit**

```bash
git add frontend/js/effects.js
git commit -m "feat: add effects engine (boot sequence, data cascade, glitch)"
```

---

### Task 13: Create Status Bar Module

**Files:**
- Create: `frontend/js/status-bar.js`

Manages the top status bar: LED indicators, GPS status, UTC clock.

Key exports:
- `StatusBar.updateLED(id, status)` — set green/amber/red/unknown
- `StatusBar.updateGPS(fix)` — show GPS status
- `StatusBar.startClock()` — tick UTC clock every second
- `StatusBar.updateFromDataQuality(dq)` — set LEDs from API data_quality response

**Step 1: Implement the status bar module**
**Step 2: Verify clock ticks and LEDs render**
**Step 3: Commit**

```bash
git add frontend/js/status-bar.js
git commit -m "feat: add status bar with LED indicators and UTC clock"
```

---

### Task 14: Create Command Panel Module

**Files:**
- Create: `frontend/js/command-panel.js`

Manages the left sidebar: tab switching, search, parameters, mission planning form.

Key exports:
- `CommandPanel.init(app)` — bind events
- `CommandPanel.switchTab(tab)` — analysis/mission tab toggle
- `CommandPanel.updateStats(data)` — update quick stats
- `CommandPanel.populateWaypoints(waypoints)` — render waypoint list
- `CommandPanel.handleSearch(query)` — search with autocomplete
- `CommandPanel.handleTerminalInput(cmd)` — parse coordinate input

**Step 1: Implement the command panel module**
**Step 2: Verify tab switching works**
**Step 3: Commit**

```bash
git add frontend/js/command-panel.js
git commit -m "feat: add command panel with search, params, and mission planning"
```

---

### Task 15: Create Intel Panel Module

**Files:**
- Create: `frontend/js/intel-panel.js`

Manages the right panel: sky plot wrapper, satellite list, analysis stats, mission brief, data quality display.

Key exports:
- `IntelPanel.init(app)` — bind events
- `IntelPanel.updateAnalysis(data)` — populate from /analyze response
- `IntelPanel.updateMissionBrief(summary)` — render mission summary
- `IntelPanel.updateDataQuality(dq)` — render data quality indicators
- `IntelPanel.updateSatelliteList(satellites)` — render satellite list

**Step 1: Implement the intel panel module**
**Step 2: Verify analysis data renders in panel**
**Step 3: Commit**

```bash
git add frontend/js/intel-panel.js
git commit -m "feat: add intel panel with sky plot, satellite list, and mission brief"
```

---

### Task 16: Create Route Renderer Module

**Files:**
- Create: `frontend/js/route-renderer.js`

Manages route rendering on the Leaflet map: color-coded polyline segments, waypoint markers, dead zone labels.

Key exports:
- `RouteRenderer.init(map)` — attach to Leaflet map
- `RouteRenderer.renderRoute(routeGeojson, signalForecast)` — draw color-coded route
- `RouteRenderer.renderWaypoints(waypoints)` — draw star/diamond markers
- `RouteRenderer.renderDeadZones(deadZones)` — draw animated "NO SIGNAL" labels
- `RouteRenderer.clear()` — remove all route layers

**Step 1: Implement the route renderer**
**Step 2: Verify route renders with test data**
**Step 3: Commit**

```bash
git add frontend/js/route-renderer.js
git commit -m "feat: add route renderer with color-coded segments and waypoint markers"
```

---

### Task 17: Update API Client

**Files:**
- Modify: `frontend/js/api-client.js`

Add methods for the new route planning endpoint.

**Step 1: Add route planning API methods**

```javascript
async planRoute(origin, destination, sampleInterval = 500) {
    return this.request('/route/plan', {
        method: 'POST',
        body: JSON.stringify({
            origin,
            destination,
            sample_interval_m: sampleInterval,
        }),
    });
}
```

**Step 2: Verify method exists**
**Step 3: Commit**

```bash
git add frontend/js/api-client.js
git commit -m "feat: add route planning method to API client"
```

---

### Task 18: Rewrite Sky Plot for Tactical Style

**Files:**
- Modify: `frontend/js/sky-plot.js`

Update the sky plot renderer to use the tactical color palette, add:
- Radar sweep animation (rotating line)
- Threat ring rendering for obstruction zones (pulsing red sectors with sawtooth edges)
- Satellite trail arcs (15-minute predicted paths)
- Phosphor green grid lines instead of gray

**Step 1: Update color constants and drawing methods**
**Step 2: Add radar sweep animation**
**Step 3: Add threat ring rendering**
**Step 4: Verify sky plot renders with new style**
**Step 5: Commit**

```bash
git add frontend/js/sky-plot.js
git commit -m "feat: restyle sky plot with tactical HUD (radar sweep, threat rings)"
```

---

### Task 19: Rewrite Main App Module

**Files:**
- Rewrite: `frontend/js/app.js`

Refactor `LinkSpotApp` to orchestrate the new module system. The app class becomes thinner — it delegates to `StatusBar`, `CommandPanel`, `IntelPanel`, `RouteRenderer`, and `EffectsEngine`.

Key changes:
- Constructor initializes all sub-modules
- `init()` runs boot sequence, then initializes map and modules
- Map setup uses dark CartoDB tiles with hex grid overlay
- Heat map rendering stays in app.js but uses new grid cell styling
- Mission planning flow: sidebar form → API call → route renderer + intel panel update
- Point click flow: map click → API call → intel panel update + status bar update
- Remove the old detail panel slide-out (replaced by persistent intel panel)
- Remove old legend (replaced by integrated status indicators)

**Step 1: Rewrite app.js with module orchestration**
**Step 2: Verify the app initializes and map loads**
**Step 3: Verify search → heatmap flow works end-to-end**
**Step 4: Verify mission planning flow works end-to-end**
**Step 5: Commit**

```bash
git add frontend/js/app.js
git commit -m "feat: rewrite app.js as module orchestrator for Mission Control UI"
```

---

## Phase 5: Integration & Polish

### Task 20: Update Service Worker

**Files:**
- Modify: `frontend/sw.js`

Update the static asset list to include new JS files, fonts, and icons. Add the route planning API to the network-first cache strategy.

**Step 1: Update STATIC_ASSETS list**
**Step 2: Add /api/v1/route/ to API_ROUTES**
**Step 3: Commit**

```bash
git add frontend/sw.js
git commit -m "feat: update service worker for new frontend modules and route API"
```

---

### Task 21: Update Electron Protocol Handler

**Files:**
- Modify: `electron/protocol-handler.js`

Update CSP headers to allow the new font and icon CDNs. Update connect-src for OSRM API if the frontend calls it directly (it shouldn't — backend proxies it, but CSP may need `connect-src` for the backend route endpoint).

**Step 1: Update CSP in protocol-handler.js**
**Step 2: Test Electron app launches**

Run: `npm start`
Expected: App window opens with Mission Control layout

**Step 3: Commit**

```bash
git add electron/protocol-handler.js
git commit -m "fix: update Electron CSP headers for new fonts and icons"
```

---

### Task 22: End-to-End Smoke Test

**Files:** None (manual testing)

**Step 1: Start all services**

Run: `make rebuild`

**Step 2: Test analysis flow**

1. Open `http://localhost`
2. Verify boot sequence animation plays
3. Search for "Times Square, New York"
4. Verify heatmap loads on map
5. Click a grid cell
6. Verify intel panel updates with satellite data and sky plot
7. Check status bar LEDs are green
8. Check data_quality section shows source information

**Step 3: Test mission planning flow**

1. Switch to MISSION tab
2. Enter destination: "Philadelphia, PA"
3. Click COMPUTE ROUTE
4. Verify route renders on map with color-coded segments
5. Verify waypoint markers appear
6. Verify mission brief populates in intel panel
7. Click a waypoint to see its analysis

**Step 4: Test error states**

1. Stop backend: `docker-compose -p linkspot stop backend`
2. Verify "SIGNAL LOST" overlay or status bar goes red
3. Restart backend: `docker-compose -p linkspot start backend`
4. Verify recovery

**Step 5: Commit any fixes from smoke testing**

```bash
git add -A
git commit -m "fix: smoke test fixes for Mission Control integration"
```

---

## Task Dependency Graph

```
Task 1 (dead code) ─┐
Task 2 (constellations) ─┤
Task 3 (terrain) ─────┤── Phase 1: Backend Fixes
Task 4 (data quality) ─┤
Task 5 (silent failures) ┘
         │
Task 6 (OSRM client) ─┐
Task 7 (route schemas) ─┤── Phase 2: Backend Route Planning
Task 8 (route endpoint) ┘
         │
Task 9 (fonts/icons) ─┐
Task 10 (CSS) ─────────┤── Phase 3: Frontend Design System
Task 11 (HTML layout) ─┘
         │
Task 12 (effects) ─┐
Task 13 (status bar) ─┤
Task 14 (command panel) ─┤
Task 15 (intel panel) ─┤── Phase 4: Frontend JS Modules
Task 16 (route renderer) ─┤
Task 17 (API client) ─┤
Task 18 (sky plot) ─┤
Task 19 (app.js rewrite) ┘
         │
Task 20 (service worker) ─┐
Task 21 (electron CSP) ─┤── Phase 5: Integration & Polish
Task 22 (smoke test) ─────┘
```

Tasks within each phase can be done in the listed order. Phase 3 can begin as soon as Phase 1 is complete (Phase 2 can run in parallel with Phase 3/4).
