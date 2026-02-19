# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# FastAPI dependencies for dependency injection.
# Provides database, cache, and engine connections.

"""FastAPI dependencies for LinkSpot API."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

import redis.asyncio as aioredis
import asyncpg
from fastapi import Depends, HTTPException, Request, status

# Configure logging
logger = logging.getLogger(__name__)

# Singleton instances (initialized on first use)
_redis_pool: Optional[aioredis.Redis] = None
_db_pool: Optional[asyncpg.Pool] = None
_satellite_engine: Optional[Any] = None
_data_pipeline: Optional[Any] = None
_obstruction_engine: Optional[Any] = None
_osrm_client: Optional[Any] = None
_amenity_service: Optional[Any] = None

# Import configuration
from config import settings


# ============================================================================
# Redis Dependency
# ============================================================================

async def get_redis_pool() -> aioredis.Redis:
    """Get or create Redis connection pool.
    
    Returns:
        aioredis.Redis: Redis client instance.
        
    Raises:
        HTTPException: If Redis connection fails.
    """
    global _redis_pool
    
    if _redis_pool is None:
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
            logger.error(f"Failed to connect to Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache service unavailable"
            )
    
    return _redis_pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency for Redis connection.

    Yields:
        aioredis.Redis: Redis client for request scope.
    """
    redis = await get_redis_pool()
    try:
        yield redis
    except aioredis.RedisError as e:
        logger.error(f"Redis operation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache operation failed"
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
        try:
            _db_pool = await asyncpg.create_pool(
                str(settings.database_url),
                min_size=5,
                max_size=settings.database_pool_size,
                max_inactive_connection_lifetime=300,
                command_timeout=30,
                server_settings={
                    "application_name": "linkspot_api",
                    "jit": "off",  # Disable JIT for short queries
                },
            )
            # Test connection
            async with _db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service unavailable"
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
                detail="Database query failed"
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

    Uses real SatelliteEngine (CelesTrak TLE data + Skyfield).
    """
    global _satellite_engine

    if _satellite_engine is None:
        sync_redis = _get_sync_redis()
        _satellite_engine = _SatelliteEngineAdapter(sync_redis)
        logger.info("Satellite engine initialized (real — CelesTrak/Skyfield)")

    return _satellite_engine


def _get_sync_redis():
    """Create a synchronous Redis client for real engines.

    NOTE: decode_responses must be False (default) because the data pipeline
    calls .decode('utf-8') on cached GeoJSON bytes.  Setting it to True
    causes "'str' object has no attribute 'decode'" errors.
    """
    import redis as sync_redis
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
        self._engine = SatelliteEngine(sync_redis)
        self._engine.fetch_tle_data()
        logger.info(f"Loaded {len(self._engine._satellites)} satellites from TLE data")

    async def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> list[dict]:
        import asyncio
        positions = await asyncio.to_thread(
            self._engine.get_satellite_positions,
            lat, lon, elevation, timestamp,
        )
        return [
            {
                "satellite_id": p.satellite_id,
                "name": p.name,
                "azimuth": p.azimuth,
                "elevation": p.elevation,
                "range_km": p.range_km,
                "is_visible": p.is_visible,
            }
            for p in positions
        ]

    async def get_constellations(self) -> list[dict]:
        metadata = await asyncio.to_thread(self._engine.get_constellation_metadata)
        return [metadata]


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
        _data_pipeline = _DataPipelineAdapter(sync_redis, postgis_url)
        logger.info("Data pipeline initialized (real — Overture/OSM)")

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
            self._pipeline.get_buildings_in_radius, lat, lon, radius_m,
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
            buildings.append({
                "lat": centroid.y,
                "lon": centroid.x,
                "height": height,
                "ground_elevation": 0.0,
                "geometry": mapping(row.geometry),
            })
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
            return [{
                "lat": lat,
                "lon": lon,
                "elevation": float(elevation),
                "source": "copernicus_glo30",
            }]
        except Exception as e:
            logger.warning("Terrain data unavailable: %s", str(e))
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
        self.min_elevation = 25.0
        self.sat_threshold = 4

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
        from enu_utils import wgs84_to_enu, azimuth_to_sector_index

        # Filter satellites above minimum elevation
        visible_sats = [
            s for s in satellites
            if s.get("elevation", 0) >= self.min_elevation
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
            b_lats = np.array([b.get("lat", 0.0) for b in buildings])
            b_lons = np.array([b.get("lon", 0.0) for b in buildings])
            b_heights = np.array([b.get("height", 10.0) for b in buildings])
            b_base = np.array([b.get("ground_elevation", 0.0) for b in buildings])

            e, n, u = wgs84_to_enu(b_lats, b_lons, b_base, lat, lon, elevation)

            h_dists = np.sqrt(e ** 2 + n ** 2)
            valid = h_dists > 0.1

            if np.any(valid):
                e_v = e[valid]
                n_v = n[valid]
                h_v = b_heights[valid]
                base_v = b_base[valid]
                h_d = h_dists[valid]

                azimuths = np.mod(np.degrees(np.arctan2(e_v, n_v)), 360.0)
                roof_heights = base_v + h_v
                elev_angles = np.degrees(np.arctan2(roof_heights - elevation, h_d))

                sectors = azimuth_to_sector_index(azimuths, self.sector_width)
                for sector in np.unique(sectors):
                    mask = sectors == sector
                    obstruction_profile[sector] = max(
                        obstruction_profile[sector],
                        float(np.max(elev_angles[mask])),
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
            satellite_details.append({
                "satellite_id": sat.get("satellite_id", ""),
                "name": sat.get("name", ""),
                "azimuth": az,
                "elevation": el,
                "range_km": sat.get("range_km"),
                "is_visible": sat.get("is_visible", True),
                "is_obstructed": is_obstructed,
            })

        # Build obstruction profile points for sky plot
        obstruction_points = []
        for i in range(self.n_sectors):
            if obstruction_profile[i] > -90.0:
                az_center = i * self.sector_width + self.sector_width / 2
                obstruction_points.append({
                    "azimuth": az_center,
                    "elevation": max(0.0, float(obstruction_profile[i])),
                })

        obstruction_pct = (len(blocked_azimuths) / n_total * 100.0) if n_total > 0 else 0.0

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

    def query_amenities_along_route(
        self, geometry: list[tuple[float, float]], buffer_m: float = 500.0
    ) -> list[dict]:
        """Query OSM Overpass for parking/rest amenities near route geometry."""
        import requests

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
          node["amenity"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="fuel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["highway"="rest_area"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="restaurant"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="fast_food"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          node["amenity"="cafe"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
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
            payload = resp.json()
        except Exception as e:
            logger.warning("Amenity query failed: %s", str(e))
            return []

        amenities = []
        for element in payload.get("elements", []):
            lat = element.get("lat") or element.get("center", {}).get("lat")
            lon = element.get("lon") or element.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue

            tags = element.get("tags", {})
            amenity_type = tags.get("amenity", tags.get("highway", "unknown"))
            tags_str = str(tags).lower()

            amenities.append({
                "lat": float(lat),
                "lon": float(lon),
                "type": amenity_type,
                "name": tags.get("name", ""),
                "parking": amenity_type in ("parking", "rest_area"),
                "restroom": ("toilets" in tags_str) or ("restroom" in tags_str),
                "fuel": amenity_type == "fuel",
                "food": amenity_type in ("restaurant", "fast_food", "cafe"),
            })

        return amenities


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
    redis: aioredis.Redis = Depends(get_redis),
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
