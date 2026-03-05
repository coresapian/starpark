# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# FastAPI dependencies for dependency injection.
# Provides database, cache, and engine connections.

"""FastAPI dependencies for LinkSpot API."""

import asyncio
import logging
import math
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

import asyncpg
from fastapi import Depends, HTTPException, Request, status

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover - environment-dependent optional dependency
    aioredis = None

# Configure logging
logger = logging.getLogger(__name__)

# Singleton instances (initialized on first use)
_redis_pool: Optional[Any] = None
_db_pool: Optional[asyncpg.Pool] = None
_satellite_engine: Optional[Any] = None
_data_pipeline: Optional[Any] = None
_obstruction_engine: Optional[Any] = None
_osrm_client: Optional[Any] = None
_amenity_service: Optional[Any] = None

# Import configuration
from config import settings


class _NoopRedis:
    """Minimal async Redis-compatible shim for degraded mode."""

    async def ping(self) -> bool:
        return False

    async def get(self, _key: str) -> None:
        return None

    async def setex(self, _key: str, _ttl: int, _value: str) -> bool:
        return False

    async def close(self) -> None:
        return None


class _NoopSyncRedis:
    """Minimal sync Redis-compatible shim for degraded mode."""

    def ping(self) -> bool:
        return False

    def get(self, _key: str) -> None:
        return None

    def ttl(self, _key: str) -> int:
        return -2

    def setex(self, _key: str, _ttl: int, _value: bytes | str) -> bool:
        return False

    def set(self, _key: str, _value: bytes | str, ex: int | None = None) -> bool:
        return False

    def delete(self, *_keys: str) -> int:
        return 0

    def exists(self, _key: str) -> int:
        return 0

    def keys(self, _pattern: str = "*") -> list[str]:
        return []

    def scan_iter(self, _pattern: str = "*"):
        return iter(())


# ============================================================================
# Redis Dependency
# ============================================================================


async def get_redis_pool() -> Any:
    """Get or create Redis connection pool.

    Returns:
        aioredis.Redis: Redis client instance.

    Raises:
        HTTPException: If Redis connection fails.
    """
    global _redis_pool

    if _redis_pool is None:
        if aioredis is None:
            logger.warning("redis package not installed; using degraded noop cache")
            _redis_pool = _NoopRedis()
        else:
            try:
                _redis_pool = aioredis.from_url(
                    str(settings.redis_url),
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=settings.redis_pool_size,
                    socket_timeout=settings.redis_socket_timeout,
                    socket_connect_timeout=settings.redis_socket_connect_timeout,
                )
                # Test connection
                await _redis_pool.ping()
                logger.info("Redis connection pool initialized")
            except Exception as e:
                logger.warning("Redis unavailable; using degraded noop cache: %s", e)
                _redis_pool = _NoopRedis()

    return _redis_pool


async def get_redis() -> AsyncGenerator[Any, None]:
    """FastAPI dependency for Redis connection.

    Yields:
        aioredis.Redis: Redis client for request scope.
    """
    redis = await get_redis_pool()
    try:
        yield redis
    except Exception as e:
        logger.error(f"Redis operation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache operation failed",
        )


# ============================================================================
# Database Dependency
# ============================================================================


async def get_db_pool() -> asyncpg.Pool:
    """Get or create PostgreSQL connection pool.

    Returns:
        asyncpg.Pool: Database connection pool.

    Raises:
        HTTPException: If database connection fails.
    """
    global _db_pool

    if _db_pool is None:
        attempts = 3
        base_backoff = 0.3
        for attempt in range(1, attempts + 1):
            try:
                _db_pool = await asyncpg.create_pool(
                    str(settings.database_url),
                    min_size=max(1, min(5, settings.database_pool_size)),
                    max_size=settings.database_pool_size,
                    max_inactive_connection_lifetime=300,
                    command_timeout=settings.request_timeout_seconds,
                    server_settings={
                        "application_name": "linkspot_api",
                        "jit": "off",  # Disable JIT for short queries
                    },
                )
                async with _db_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                logger.info("Database connection pool initialized")
                break
            except Exception as e:
                logger.warning(
                    "DB pool init attempt %d/%d failed: %s", attempt, attempts, e
                )
                if attempt == attempts:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Database service unavailable",
                    ) from e
                await asyncio.sleep(
                    base_backoff * (2 ** (attempt - 1)) + random.uniform(0.0, 0.15)
                )

    return _db_pool


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """FastAPI dependency for database connection.

    Yields:
        asyncpg.Connection: Database connection for request scope.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            yield conn
        except asyncpg.PostgresError as e:
            logger.error(f"Database query failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database query failed",
            )


@asynccontextmanager
async def get_db_transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager for database transactions.

    Usage:
        async with get_db_transaction() as conn:
            result = await conn.fetch("SELECT ...")
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# ============================================================================
# Satellite Engine Dependency
# ============================================================================


async def get_satellite_engine() -> Any:
    """Get or initialize satellite engine singleton.

    Uses real SatelliteEngine (Space-Track GP preferred, CelesTrak fallback).
    """
    global _satellite_engine

    if _satellite_engine is None:
        sync_redis = _get_sync_redis()
        try:
            _satellite_engine = _SatelliteEngineAdapter(sync_redis)
            logger.info(
                "Satellite engine initialized (real — Space-Track/CelesTrak + Skyfield)"
            )
        except Exception as e:
            logger.warning(
                "Satellite engine unavailable; using degraded fallback: %s", e
            )
            _satellite_engine = _FallbackSatelliteEngine(reason=str(e))

    return _satellite_engine


def _get_sync_redis():
    """Create a synchronous Redis client for real engines.

    NOTE: decode_responses must be False (default) because the data pipeline
    calls .decode('utf-8') on cached GeoJSON bytes.  Setting it to True
    causes "'str' object has no attribute 'decode'" errors.
    """
    try:
        import redis as sync_redis
    except ImportError:
        logger.warning("redis package not installed; using degraded sync noop cache")
        return _NoopSyncRedis()
    return sync_redis.Redis.from_url(
        str(settings.redis_url),
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


class _SatelliteEngineAdapter:
    """Wraps real SatelliteEngine to match the async router interface."""

    def __init__(self, sync_redis):
        from satellite_engine import SatelliteEngine

        self._engine = SatelliteEngine(
            sync_redis,
            space_track_identity=settings.spacetrack_identity,
            space_track_password=settings.spacetrack_password,
            space_track_min_interval_seconds=settings.spacetrack_gp_min_interval_seconds,
            space_track_per_minute_limit=settings.spacetrack_rate_limit_per_minute,
            space_track_per_hour_limit=settings.spacetrack_rate_limit_per_hour,
            space_track_timeout_seconds=settings.spacetrack_http_timeout_seconds,
        )
        self._engine.fetch_tle_data()
        logger.info(f"Loaded {len(self._engine._satellites)} satellites from TLE data")
        # TODO: Move TLE refresh to a background updater to prevent stale ephemeris during long-lived sessions.

    async def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> list[dict]:
        # TODO: Add input range validation and request cancellation handling for long satellite solves.
        import asyncio

        positions = await asyncio.to_thread(
            self._engine.get_satellite_positions,
            lat,
            lon,
            elevation,
            timestamp,
        )
        return [
            {
                "satellite_id": p.satellite_id,
                "norad_id": p.norad_id,
                "name": p.name,
                "azimuth": p.azimuth,
                "elevation": p.elevation,
                "range_km": p.range_km,
                "latitude": p.latitude,
                "longitude": p.longitude,
                "altitude_km": p.altitude_km,
                "velocity_kms": p.velocity_kms,
                "constellation": p.constellation,
                "is_visible": p.is_visible,
            }
            for p in positions
        ]

    async def get_constellations(self) -> list[dict]:
        metadata = await asyncio.to_thread(self._engine.get_constellation_metadata)
        return [metadata]

    async def get_constellation_map_positions(
        self,
        timestamp: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        positions = await asyncio.to_thread(
            self._engine.get_constellation_positions,
            timestamp,
            limit,
        )
        source = await asyncio.to_thread(self._engine.get_tle_source)
        return {
            "satellites": positions,
            "source": source,
        }


class _FallbackSatelliteEngine:
    """Fallback satellite engine used when optional runtime deps are unavailable."""

    def __init__(self, reason: str):
        self._reason = reason

    async def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> list[dict]:
        return []

    async def get_constellations(self) -> list[dict]:
        return [{"name": "unavailable", "status": "degraded", "reason": self._reason}]

    async def get_constellation_map_positions(
        self,
        timestamp: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        _ = timestamp
        _ = limit
        return {
            "satellites": [],
            "source": f"degraded:{self._reason}",
        }


# ============================================================================
# Data Pipeline Dependency
# ============================================================================


async def get_data_pipeline() -> Any:
    """Get or initialize data pipeline singleton.

    Uses real LinkSpotDataPipeline (Overture/OSM building data).
    """
    global _data_pipeline

    if _data_pipeline is None:
        sync_redis = _get_sync_redis()
        postgis_url = str(settings.database_url).replace("+asyncpg", "")
        try:
            _data_pipeline = _DataPipelineAdapter(sync_redis, postgis_url)
            logger.info("Data pipeline initialized (real — Overture/OSM)")
        except Exception as e:
            logger.warning("Data pipeline unavailable; using degraded fallback: %s", e)
            _data_pipeline = _FallbackDataPipeline(reason=str(e))

    return _data_pipeline


class _DataPipelineAdapter:
    """Wraps real LinkSpotDataPipeline to match the async router interface."""

    def __init__(self, sync_redis, postgis_conn=None):
        from data_pipeline import LinkSpotDataPipeline

        self._pipeline = LinkSpotDataPipeline(
            redis_client=sync_redis,
            postgis_conn_string=postgis_conn,
        )
        self._terrain_client = None

    async def fetch_buildings(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> tuple[list[dict], str]:
        import asyncio
        from shapely.geometry import mapping

        gdf = await asyncio.to_thread(
            self._pipeline.get_buildings_in_radius,
            lat,
            lon,
            radius_m,
        )
        if gdf is None or gdf.empty:
            return [], "none"
        buildings = []
        source = "unknown"
        if "source" in gdf.columns and not gdf["source"].isna().all():
            source = str(gdf["source"].dropna().iloc[0])
        for _, row in gdf.iterrows():
            centroid = row.geometry.centroid
            height = row.get("height", None)
            try:
                height = float(height)
            except Exception:
                height = 10.0
            if height <= 0:
                height = 10.0
            buildings.append(
                {
                    "lat": centroid.y,
                    "lon": centroid.x,
                    "height": height,
                    "ground_elevation": 0.0,
                    "geometry": mapping(row.geometry),
                }
            )
        return buildings, source

    async def fetch_terrain(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> list[dict]:
        try:
            from terrain_client import CopernicusTerrainClient

            if self._terrain_client is None:
                self._terrain_client = CopernicusTerrainClient()

            elevation = await asyncio.to_thread(
                self._terrain_client.get_elevation, lat, lon
            )
            if elevation is None:
                return []
            return [
                {
                    "lat": lat,
                    "lon": lon,
                    "elevation": float(elevation),
                    "source": "copernicus_glo30",
                }
            ]
        except Exception as e:
            logger.warning("Terrain data unavailable: %s", str(e))
            return []


class _FallbackDataPipeline:
    """Fallback data pipeline used when optional runtime deps are unavailable."""

    def __init__(self, reason: str):
        self._reason = reason

    async def fetch_buildings(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> tuple[list[dict], str]:
        return [], f"degraded:{self._reason}"

    async def fetch_terrain(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> list[dict]:
        return []


# ============================================================================
# Obstruction Engine Dependency
# ============================================================================


async def get_obstruction_engine() -> Any:
    """Get or initialize obstruction engine singleton.

    Uses real ray-casting logic from ray_casting_engine.py.
    Accepts pre-fetched building/satellite data for heatmap efficiency.
    """
    global _obstruction_engine

    if _obstruction_engine is None:
        _obstruction_engine = _ObstructionEngineAdapter()
        logger.info("Obstruction engine initialized (ray-casting)")

    return _obstruction_engine


class _ObstructionEngineAdapter:
    """Real ray-casting obstruction analysis, accepting pre-fetched data.

    Implements the same algorithm as ObstructionEngine.analyze_position()
    but accepts buildings/satellites as parameters for heatmap batch efficiency.
    """

    def __init__(self):
        self.sector_width = 2.0
        self.n_sectors = int(360.0 / self.sector_width)
        self.min_elevation = float(settings.elevation_mask_degrees)
        self.sat_threshold = 4

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_footprint_vertices(
        self, building: dict[str, Any]
    ) -> list[tuple[float, float]]:
        geometry = building.get("geometry")
        if not isinstance(geometry, dict):
            return []

        geom_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates:
            return []

        rings: list[list[Any]] = []
        if geom_type == "Polygon":
            if coordinates and isinstance(coordinates[0], list):
                rings.append(coordinates[0])
        elif geom_type == "MultiPolygon":
            for polygon in coordinates:
                if (
                    isinstance(polygon, list)
                    and polygon
                    and isinstance(polygon[0], list)
                ):
                    rings.append(polygon[0])
        else:
            return []

        vertices: list[tuple[float, float]] = []
        for ring in rings:
            for coord in ring:
                if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                    continue
                lon = self._to_float(coord[0], float("nan"))
                lat = self._to_float(coord[1], float("nan"))
                if not (math.isfinite(lat) and math.isfinite(lon)):
                    continue
                vertices.append((lat, lon))

        return vertices

    def _sector_span(self, sectors: list[int]) -> list[int]:
        unique = sorted(set(sectors))
        if not unique:
            return []
        if len(unique) == 1:
            return unique

        gaps: list[int] = []
        for idx, sector in enumerate(unique):
            next_sector = unique[(idx + 1) % len(unique)]
            gaps.append((next_sector - sector) % self.n_sectors)

        max_gap_idx = max(range(len(gaps)), key=lambda idx: gaps[idx])
        start = unique[(max_gap_idx + 1) % len(unique)]
        end = unique[max_gap_idx]

        covered: list[int] = []
        current = start
        while True:
            covered.append(current)
            if current == end:
                break
            current = (current + 1) % self.n_sectors

        return covered

    def _update_profile_from_building(
        self,
        obstruction_profile: Any,
        observer_lat: float,
        observer_lon: float,
        observer_elev: float,
        building: dict[str, Any],
    ) -> None:
        import numpy as np
        from enu_utils import azimuth_to_sector_index, wgs84_to_enu

        building_height = max(0.0, self._to_float(building.get("height", 10.0), 10.0))
        base_elevation = self._to_float(building.get("ground_elevation", 0.0), 0.0)

        vertices = self._extract_footprint_vertices(building)
        if vertices:
            b_lats = np.array([coord[0] for coord in vertices], dtype=float)
            b_lons = np.array([coord[1] for coord in vertices], dtype=float)
            b_base = np.full(len(vertices), base_elevation, dtype=float)
        else:
            b_lat = self._to_float(building.get("lat", observer_lat), observer_lat)
            b_lon = self._to_float(building.get("lon", observer_lon), observer_lon)
            b_lats = np.array([b_lat], dtype=float)
            b_lons = np.array([b_lon], dtype=float)
            b_base = np.array([base_elevation], dtype=float)

        e, n, _u = wgs84_to_enu(
            b_lats,
            b_lons,
            b_base,
            observer_lat,
            observer_lon,
            observer_elev,
        )

        horizontal = np.sqrt(e**2 + n**2)
        valid = horizontal > 0.1
        if not np.any(valid):
            return

        e_valid = e[valid]
        n_valid = n[valid]
        horizontal_valid = horizontal[valid]
        roof_heights = b_base[valid] + building_height

        azimuths = np.mod(np.degrees(np.arctan2(e_valid, n_valid)), 360.0)
        elevations = np.degrees(
            np.arctan2(roof_heights - observer_elev, horizontal_valid)
        )
        sectors = azimuth_to_sector_index(azimuths, self.sector_width)
        if sectors.size == 0:
            return

        covered_sectors = self._sector_span([int(value) for value in sectors.tolist()])
        if not covered_sectors:
            return

        max_elevation = float(np.max(elevations))
        for sector in covered_sectors:
            obstruction_profile[sector] = max(
                obstruction_profile[sector], max_elevation
            )

    def _update_profile_from_terrain(
        self,
        obstruction_profile: Any,
        observer_lat: float,
        observer_lon: float,
        observer_elev: float,
        terrain: list[dict[str, Any]],
    ) -> None:
        import numpy as np
        from enu_utils import azimuth_to_sector_index, wgs84_to_enu

        valid_samples: list[tuple[float, float, float]] = []
        for sample in terrain:
            if not isinstance(sample, dict):
                continue
            t_lat = self._to_float(sample.get("lat"), float("nan"))
            t_lon = self._to_float(sample.get("lon"), float("nan"))
            t_elev = self._to_float(sample.get("elevation"), float("nan"))
            if not (
                math.isfinite(t_lat) and math.isfinite(t_lon) and math.isfinite(t_elev)
            ):
                continue
            if abs(t_lat - observer_lat) < 1e-7 and abs(t_lon - observer_lon) < 1e-7:
                continue
            valid_samples.append((t_lat, t_lon, t_elev))

        if not valid_samples:
            return

        t_lats = np.array([sample[0] for sample in valid_samples], dtype=float)
        t_lons = np.array([sample[1] for sample in valid_samples], dtype=float)
        t_elevs = np.array([sample[2] for sample in valid_samples], dtype=float)

        e, n, u = wgs84_to_enu(
            t_lats,
            t_lons,
            t_elevs,
            observer_lat,
            observer_lon,
            observer_elev,
        )
        horizontal = np.sqrt(e**2 + n**2)
        valid = horizontal > 0.1
        if not np.any(valid):
            return

        azimuths = np.mod(np.degrees(np.arctan2(e[valid], n[valid])), 360.0)
        terrain_elev = np.degrees(np.arctan2(u[valid], horizontal[valid]))
        sectors = azimuth_to_sector_index(azimuths, self.sector_width)
        for idx, sector in enumerate(sectors.tolist()):
            obstruction_profile[int(sector)] = max(
                obstruction_profile[int(sector)], float(terrain_elev[idx])
            )

    def analyze_position(
        self,
        lat: float,
        lon: float,
        elevation: float,
        buildings: list[dict],
        terrain: list[dict],
        satellites: list[dict],
    ) -> dict:
        """Perform ray-casting obstruction analysis at a single position."""
        import numpy as np
        from enu_utils import azimuth_to_sector_index

        # Filter satellites above minimum elevation
        visible_sats = [
            s for s in satellites if s.get("elevation", 0) >= self.min_elevation
        ]
        n_total = len(visible_sats)

        if n_total == 0:
            return {
                "n_clear": 0,
                "n_total": 0,
                "obstruction_pct": 100.0,
                "blocked_azimuths": [],
            }

        # Build obstruction profile from buildings
        obstruction_profile = np.full(self.n_sectors, -90.0)

        if buildings:
            for building in buildings:
                if not isinstance(building, dict):
                    continue
                self._update_profile_from_building(
                    obstruction_profile=obstruction_profile,
                    observer_lat=lat,
                    observer_lon=lon,
                    observer_elev=elevation,
                    building=building,
                )

        if terrain:
            self._update_profile_from_terrain(
                obstruction_profile=obstruction_profile,
                observer_lat=lat,
                observer_lon=lon,
                observer_elev=elevation,
                terrain=terrain,
            )

        # Check each satellite for clear LOS and build per-satellite detail
        n_clear = 0
        blocked_azimuths = []
        satellite_details = []
        for sat in visible_sats:
            az = sat.get("azimuth", 0.0)
            el = sat.get("elevation", 0.0)
            sector = int(azimuth_to_sector_index(np.array([az]), self.sector_width)[0])
            is_obstructed = el <= obstruction_profile[sector]
            if not is_obstructed:
                n_clear += 1
            else:
                blocked_azimuths.append(az)
            satellite_details.append(
                {
                    "satellite_id": sat.get("satellite_id", ""),
                    "name": sat.get("name", ""),
                    "azimuth": az,
                    "elevation": el,
                    "range_km": sat.get("range_km"),
                    "is_visible": sat.get("is_visible", True),
                    "is_obstructed": is_obstructed,
                }
            )

        # Build obstruction profile points for sky plot
        obstruction_points = []
        for i in range(self.n_sectors):
            if obstruction_profile[i] > -90.0:
                az_center = i * self.sector_width + self.sector_width / 2
                obstruction_points.append(
                    {
                        "azimuth": az_center,
                        "elevation": max(0.0, float(obstruction_profile[i])),
                    }
                )

        obstruction_pct = (
            (len(blocked_azimuths) / n_total * 100.0) if n_total > 0 else 0.0
        )

        return {
            "n_clear": n_clear,
            "n_total": n_total,
            "obstruction_pct": round(obstruction_pct, 2),
            "blocked_azimuths": blocked_azimuths,
            "satellite_details": satellite_details,
            "obstruction_profile": obstruction_points,
        }


# ============================================================================
# Route Planning Dependencies
# ============================================================================


async def get_osrm_client() -> Any:
    """Get or initialize OSRM client singleton."""
    global _osrm_client

    if _osrm_client is None:
        from osrm_client import OSRMClient

        _osrm_client = OSRMClient()
        logger.info("OSRM client initialized")

    return _osrm_client


class _AmenityService:
    """Utility service for geocoding and route-adjacent amenity lookups."""

    def geocode_address(self, address: str) -> tuple[float, float]:
        """Geocode an address using Nominatim."""
        import requests
        # TODO: Centralize outbound geocoder settings (UA, timeout, fallback provider) and add response validation.

        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "LinkSpot/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise ValueError(f"Could not geocode address: {address}")
        return float(results[0]["lat"]), float(results[0]["lon"])

    def __init__(self):
        self._overpass_failures = 0
        self._overpass_blocked_until = 0.0
        self._road_mask_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._road_mask_ttl_seconds = 180.0

    def _request_overpass(
        self, query: str, timeout_s: float = 15.0
    ) -> Optional[dict[str, Any]]:
        import requests

        now = time.time()
        if self._overpass_blocked_until > now:
            logger.warning("Overpass circuit open, skipping request")
            return None

        overpass_hosts = [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.openstreetmap.fr/api/interpreter",
        ]
        last_error: Optional[Exception] = None

        for host in overpass_hosts:
            try:
                response = requests.post(
                    host,
                    data={"data": query},
                    timeout=timeout_s,
                )
                response.raise_for_status()
                payload = response.json()
                self._overpass_failures = 0
                self._overpass_blocked_until = 0.0
                return payload
            except Exception as exc:
                last_error = exc
                logger.warning("Overpass host failed (%s): %s", host, exc)

        self._overpass_failures += 1
        if self._overpass_failures >= 3:
            self._overpass_blocked_until = time.time() + 120.0
        if last_error:
            logger.warning("Overpass request failed: %s", last_error)
        return None

    def query_amenities_along_route(
        self, geometry: list[tuple[float, float]], buffer_m: float = 500.0
    ) -> list[dict]:
        """Query OSM Overpass for parking/rest amenities near route geometry."""
        if not geometry:
            return []

        # Approximate buffer expansion in degrees.
        buffer_deg = max(0.001, float(buffer_m) / 111000.0)
        lats = [p[0] for p in geometry]
        lons = [p[1] for p in geometry]
        bbox = (
            min(lats) - buffer_deg,
            min(lons) - buffer_deg,
            max(lats) + buffer_deg,
            max(lons) + buffer_deg,
        )

        query = f"""
        [out:json][timeout:30];
        (
          node["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="fuel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["highway"="services"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out center;
        """

        payload = self._request_overpass(query, timeout_s=15.0)
        if not payload:
            return []

        amenities = []
        seen: set[str] = set()
        for element in payload.get("elements", []):
            lat = element.get("lat") or element.get("center", {}).get("lat")
            lon = element.get("lon") or element.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue

            tags = element.get("tags", {})
            amenity_type = tags.get("amenity", tags.get("highway", "unknown"))
            if amenity_type not in {"parking", "fuel", "rest_area", "services"}:
                continue

            key = f"{amenity_type}:{float(lat):.5f}:{float(lon):.5f}"
            if key in seen:
                continue
            seen.add(key)

            tags_str = str(tags).lower()

            amenities.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "type": amenity_type,
                    "name": tags.get("name", ""),
                    "parking": amenity_type in ("parking", "rest_area", "services"),
                    "restroom": ("toilets" in tags_str) or ("restroom" in tags_str),
                    "fuel": amenity_type == "fuel",
                    "food": False,
                }
            )

        return amenities

    def query_road_access_mask(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
    ) -> dict[str, Any]:
        bbox = (
            min(min_lat, max_lat),
            min(min_lon, max_lon),
            max(min_lat, max_lat),
            max(min_lon, max_lon),
        )
        cache_key = f"{bbox[0]:.4f}:{bbox[1]:.4f}:{bbox[2]:.4f}:{bbox[3]:.4f}"
        now = time.time()
        cached = self._road_mask_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        query = f"""
        [out:json][timeout:35];
        (
          way["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service|road"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="parking"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="fuel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["highway"="services"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out body;
        >;
        out skel qt;
        """

        payload = self._request_overpass(query, timeout_s=20.0)
        if not payload:
            return {"roads": [], "parking_polygons": [], "parking_points": []}

        driveable_highways = {
            "motorway",
            "motorway_link",
            "trunk",
            "trunk_link",
            "primary",
            "primary_link",
            "secondary",
            "secondary_link",
            "tertiary",
            "tertiary_link",
            "unclassified",
            "residential",
            "living_street",
            "service",
            "road",
        }

        nodes: dict[int, tuple[float, float]] = {}
        ways: list[dict[str, Any]] = []
        parking_points: list[tuple[float, float]] = []

        for element in payload.get("elements", []):
            if not isinstance(element, dict):
                continue
            if element.get("type") == "node":
                node_id = element.get("id")
                lat = element.get("lat")
                lon = element.get("lon")
                if node_id is not None and lat is not None and lon is not None:
                    nodes[int(node_id)] = (float(lat), float(lon))

                tags = element.get("tags", {})
                amenity = tags.get("amenity")
                highway = tags.get("highway")
                if amenity in {"parking", "fuel"} or highway in {
                    "rest_area",
                    "services",
                }:
                    if lat is not None and lon is not None:
                        parking_points.append((float(lat), float(lon)))
            elif element.get("type") == "way":
                ways.append(element)

        roads: list[list[tuple[float, float]]] = []
        parking_polygons: list[list[tuple[float, float]]] = []

        for way in ways:
            tags = way.get("tags", {}) if isinstance(way.get("tags"), dict) else {}
            node_ids = way.get("nodes") if isinstance(way.get("nodes"), list) else []
            coords = [nodes[node_id] for node_id in node_ids if node_id in nodes]
            if len(coords) < 2:
                continue

            highway = tags.get("highway")
            if highway in driveable_highways:
                roads.append(coords)

            if tags.get("amenity") == "parking" or highway == "rest_area":
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    parking_polygons.append(coords)
                else:
                    center_lat = sum(point[0] for point in coords) / len(coords)
                    center_lon = sum(point[1] for point in coords) / len(coords)
                    parking_points.append((center_lat, center_lon))

        result = {
            "roads": roads,
            "parking_polygons": parking_polygons,
            "parking_points": parking_points,
        }
        self._road_mask_cache[cache_key] = (now + self._road_mask_ttl_seconds, result)
        return result


async def get_amenity_service() -> Any:
    """Get or initialize amenity/geocoding helper singleton."""
    global _amenity_service

    if _amenity_service is None:
        _amenity_service = _AmenityService()
        logger.info("Amenity service initialized")

    return _amenity_service


# ============================================================================
# Request ID Dependency
# ============================================================================


def get_request_id(request: Request) -> str:
    """Extract or generate request ID for tracing.

    Args:
        request: FastAPI request object.

    Returns:
        str: Request ID for logging and tracing.
    """
    # Check for existing request ID in headers
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        return request_id

    # Generate new request ID
    import uuid

    return f"req-{uuid.uuid4().hex[:12]}"


# ============================================================================
# API Key Dependency (optional)
# ============================================================================


async def verify_api_key(request: Request) -> Optional[str]:
    """Verify API key if configured.

    Args:
        request: FastAPI request object.

    Returns:
        Optional[str]: API key if valid, None if not required.

    Raises:
        HTTPException: If API key is invalid.
    """
    if not settings.api_key:
        return None  # API key not required

    api_key = request.headers.get(settings.api_key_header)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key


# ============================================================================
# Combined Dependencies
# ============================================================================


async def get_analysis_dependencies(
    redis: Any = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
) -> dict:
    """Get all analysis dependencies in one call.

    Returns:
        dict: Dictionary containing all analysis dependencies.
    """
    return {
        "redis": redis,
        "db": db,
        "satellite_engine": satellite_engine,
        "data_pipeline": data_pipeline,
        "obstruction_engine": obstruction_engine,
    }


# ============================================================================
# Cleanup Functions
# ============================================================================


async def close_dependencies() -> None:
    """Close all dependency connections.

    Call this during application shutdown.
    """
    global _redis_pool, _db_pool, _satellite_engine, _data_pipeline, _obstruction_engine
    global _osrm_client, _amenity_service

    # Close Redis
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection pool closed")

    # Close database
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed")

    # Clear engine references
    _satellite_engine = None
    _data_pipeline = None
    _obstruction_engine = None
    _osrm_client = None
    _amenity_service = None
    logger.info("Engine singletons cleared")
