# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Satellite endpoints for querying visible satellites and constellation info.

"""Satellite API endpoints for LinkSpot."""

import asyncio
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from config import settings
from dependencies import get_redis, get_request_id, get_satellite_engine
from models.schemas import (
    ConstellationInfo,
    ConstellationListResponse,
    ConstellationMapResponse,
    ConstellationMapSatellite,
    ProblemDetail,
    SatellitePosition,
    VisibleSatellitesResponse,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v1/satellites", tags=["Satellites"])


# ============================================================================
# Visible Satellites Endpoint
# ============================================================================


@router.get(
    "",
    response_model=VisibleSatellitesResponse,
    responses={
        200: {"description": "Satellites retrieved successfully"},
        400: {"model": ProblemDetail, "description": "Invalid query parameters"},
        422: {"model": ProblemDetail, "description": "Validation error"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Get currently visible satellites",
    description="""
    Returns a list of satellites currently visible from the specified location.
    
    Satellites are filtered by elevation mask (minimum elevation angle).
    Results include azimuth, elevation, and range for each satellite.
    
    **Query Parameters:**
    - `lat`: Observer latitude (-90 to 90)
    - `lon`: Observer longitude (-180 to 180)
    - `elevation`: Observer elevation above ground (optional, default 0)
    - `timestamp`: Specific time for prediction (optional, default now)
    
    **Response:**
    - List of satellite positions with azimuth, elevation, and range
    - Total count of visible satellites
    - Query timestamp and location
    """,
)
async def get_visible_satellites(
    request: Request,
    lat: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Observer latitude in decimal degrees",
        example=40.7128,
    ),
    lon: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Observer longitude in decimal degrees",
        example=-74.0060,
    ),
    elevation: float = Query(
        default=0.0,
        ge=0.0,
        le=10000.0,
        description="Observer elevation above ground level in meters",
        example=10.0,
    ),
    timestamp: Optional[datetime] = Query(
        default=None,
        description="Query timestamp (ISO 8601). Defaults to current time.",
        example="2024-06-15T12:00:00Z",
    ),
    redis: Any = Depends(get_redis),
    satellite_engine: Any = Depends(get_satellite_engine),
    request_id: str = Depends(get_request_id),
) -> VisibleSatellitesResponse:
    """Get currently visible satellites from a location.

    Args:
        request: FastAPI request object.
        lat: Observer latitude.
        lon: Observer longitude.
        elevation: Observer elevation in meters.
        timestamp: Query timestamp.
        redis: Redis connection.
        satellite_engine: Satellite engine instance.
        request_id: Request ID for tracing.

    Returns:
        VisibleSatellitesResponse: List of visible satellites.

    Raises:
        HTTPException: If query fails.
    """
    start_time = time.time()
    query_time = timestamp or datetime.now(timezone.utc)

    logger.info(
        f"[{request_id}] Getting visible satellites for "
        f"lat={lat}, lon={lon}, elevation={elevation}"
    )

    try:
        # Check cache
        cache_params = {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "elevation": elevation,
            "timestamp": query_time.isoformat(),
        }
        cache_key = f"satellites:{hashlib.sha256(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()[:16]}"

        cached_result = None
        try:
            cached_result = await redis.get(cache_key)
        except Exception as cache_error:
            logger.warning(
                "[%s] Satellite cache read unavailable: %s", request_id, cache_error
            )

        if cached_result:
            logger.info(f"[{request_id}] Cache hit for satellites")
            result = json.loads(cached_result)
            return VisibleSatellitesResponse(**result)

        # Get visible satellites from engine with timeout budget.
        satellite_data = await asyncio.wait_for(
            satellite_engine.get_visible_satellites(
                lat=lat,
                lon=lon,
                elevation=elevation,
                timestamp=query_time,
            ),
            timeout=settings.satellite_timeout_seconds,
        )

        # Convert to response model, skipping malformed records.
        satellites = []
        malformed_records = 0
        for sat in satellite_data:
            try:
                sat_elevation = float(sat.get("elevation", 0.0))
                sat_azimuth = float(sat.get("azimuth", 0.0))
                if sat_elevation < settings.elevation_mask_degrees:
                    continue

                satellites.append(
                    SatellitePosition(
                        satellite_id=str(sat.get("satellite_id", "UNKNOWN")),
                        norad_id=sat.get("norad_id"),
                        name=sat.get("name"),
                        azimuth=round(sat_azimuth % 360.0, 2),
                        elevation=round(sat_elevation, 2),
                        range_km=sat.get("range_km"),
                        velocity_kms=sat.get("velocity_kms"),
                        latitude=sat.get("latitude"),
                        longitude=sat.get("longitude"),
                        altitude_km=sat.get("altitude_km"),
                        is_visible=sat.get("is_visible"),
                        constellation=sat.get("constellation"),
                    )
                )
            except Exception:
                malformed_records += 1

        # Sort by elevation (highest first) and apply deterministic truncation.
        satellites.sort(key=lambda s: (s.elevation, s.satellite_id), reverse=True)
        if len(satellites) > settings.max_satellites_per_query:
            satellites = satellites[: settings.max_satellites_per_query]
            logger.warning(
                "[%s] Truncated results to %d records",
                request_id,
                settings.max_satellites_per_query,
            )
        if malformed_records:
            logger.warning(
                "[%s] Skipped %d malformed satellite records",
                request_id,
                malformed_records,
            )

        response = VisibleSatellitesResponse(
            satellites=satellites,
            count=len(satellites),
            timestamp=query_time,
            location={"lat": lat, "lon": lon},
            elevation_mask=settings.elevation_mask_degrees,
        )

        # Cache result (shorter TTL for satellite data); never fail request on cache write.
        try:
            await redis.setex(
                cache_key,
                60,  # 1 minute TTL for satellite positions
                json.dumps(response.model_dump(mode="json")),
            )
        except Exception as cache_error:
            logger.warning(
                "[%s] Satellite cache write unavailable: %s", request_id, cache_error
            )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[{request_id}] Found {len(satellites)} visible satellites "
            f"in {elapsed_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except asyncio.TimeoutError as e:
        logger.warning("[%s] Satellite query timed out: %s", request_id, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Satellite query timed out",
        ) from e
    except Exception as e:
        logger.error(f"[{request_id}] Failed to get satellites: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve satellites: {str(e)}",
        )


# ============================================================================
# Constellation Map Endpoint
# ============================================================================


@router.get(
    "/constellation/map",
    response_model=ConstellationMapResponse,
    responses={
        200: {"description": "Constellation map points retrieved successfully"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Get Starlink subpoint positions for map overlays",
    description="""
    Returns geodetic subpoint positions for Starlink satellites suitable for
    rendering on a world map.

    Data is sourced from Space-Track GP/TLE feeds when configured and cached
    for short intervals for responsive frontend updates.
    """,
)
async def get_constellation_map(
    request: Request,
    timestamp: Optional[datetime] = Query(
        default=None,
        description="Prediction timestamp (ISO 8601). Defaults to current time.",
        example="2024-06-15T12:00:00Z",
    ),
    limit: int = Query(
        default=settings.max_constellation_map_satellites,
        ge=100,
        le=20000,
        description="Maximum satellites to return",
    ),
    redis: Any = Depends(get_redis),
    satellite_engine: Any = Depends(get_satellite_engine),
    request_id: str = Depends(get_request_id),
) -> ConstellationMapResponse:
    """Get Starlink constellation points for map overlays."""
    query_time = timestamp or datetime.now(timezone.utc)
    effective_limit = max(100, min(limit, settings.max_constellation_map_satellites))
    start_time = time.time()

    try:
        cache_params = {
            "timestamp": query_time.replace(second=0, microsecond=0).isoformat(),
            "limit": effective_limit,
        }
        cache_key = f"constellation-map:{hashlib.sha256(json.dumps(cache_params, sort_keys=True).encode()).hexdigest()[:16]}"

        cached_result = None
        try:
            cached_result = await redis.get(cache_key)
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation map cache read unavailable: %s",
                request_id,
                cache_error,
            )

        if cached_result:
            logger.info("[%s] Cache hit for constellation map", request_id)
            return ConstellationMapResponse(**json.loads(cached_result))

        raw_result = await asyncio.wait_for(
            satellite_engine.get_constellation_map_positions(
                timestamp=query_time,
                limit=effective_limit,
            ),
            timeout=settings.satellite_timeout_seconds,
        )

        satellites_out: list[ConstellationMapSatellite] = []
        malformed = 0
        raw_satellites = (
            raw_result.get("satellites", []) if isinstance(raw_result, dict) else []
        )
        source = (
            str(raw_result.get("source", "unknown"))
            if isinstance(raw_result, dict)
            else "unknown"
        )

        for sat in raw_satellites if isinstance(raw_satellites, list) else []:
            if not isinstance(sat, dict):
                malformed += 1
                continue

            try:
                lat_raw = sat.get("latitude")
                lon_raw = sat.get("longitude")
                alt_raw = sat.get("altitude_km")
                if lat_raw is None or lon_raw is None or alt_raw is None:
                    malformed += 1
                    continue

                lat = float(lat_raw)
                lon = float(lon_raw)
                alt = float(alt_raw)
                if not (
                    math.isfinite(lat)
                    and math.isfinite(lon)
                    and math.isfinite(alt)
                    and -90.0 <= lat <= 90.0
                    and -180.0 <= lon <= 180.0
                    and alt >= 0.0
                ):
                    malformed += 1
                    continue

                norad_id_raw = sat.get("norad_id")
                norad_id = None
                if norad_id_raw is not None:
                    norad_id = int(norad_id_raw)

                velocity_raw = sat.get("velocity_kms")
                velocity_kms = None
                if velocity_raw is not None:
                    try:
                        parsed_velocity = float(velocity_raw)
                        if math.isfinite(parsed_velocity):
                            velocity_kms = parsed_velocity
                    except (TypeError, ValueError):
                        velocity_kms = None

                satellites_out.append(
                    ConstellationMapSatellite(
                        satellite_id=str(
                            sat.get("satellite_id") or sat.get("norad_id") or "UNKNOWN"
                        ),
                        norad_id=norad_id,
                        name=(str(sat.get("name")) if sat.get("name") else None),
                        latitude=lat,
                        longitude=lon,
                        altitude_km=alt,
                        velocity_kms=velocity_kms,
                        constellation=str(sat.get("constellation") or "Starlink"),
                    )
                )
            except Exception:
                malformed += 1

        if malformed:
            logger.warning(
                "[%s] Skipped %d malformed constellation map records",
                request_id,
                malformed,
            )

        response = ConstellationMapResponse(
            satellites=satellites_out,
            count=len(satellites_out),
            timestamp=query_time,
            source=source,
        )

        try:
            await redis.setex(
                cache_key,
                60,
                json.dumps(response.model_dump(mode="json")),
            )
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation map cache write unavailable: %s",
                request_id,
                cache_error,
            )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "[%s] Retrieved constellation map points (%d) in %.1fms [%s]",
            request_id,
            len(satellites_out),
            elapsed_ms,
            source,
        )
        return response

    except asyncio.TimeoutError as e:
        logger.warning("[%s] Constellation map query timed out: %s", request_id, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Constellation map query timed out",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "[%s] Failed to get constellation map: %s",
            request_id,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve constellation map: {str(e)}",
        )


# ============================================================================
# Constellation Info Endpoint
# ============================================================================


@router.get(
    "/constellation",
    response_model=ConstellationListResponse,
    responses={
        200: {"description": "Constellation info retrieved successfully"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Get constellation information",
    description="""
    Returns information about available satellite constellations.
    
    Includes details such as:
    - Constellation name and operator
    - Total and active satellite counts
    - Orbital parameters (planes, altitude, inclination)
    
    Results are cached for improved performance.
    """,
)
async def get_constellations(
    request: Request,
    redis: Any = Depends(get_redis),
    satellite_engine: Any = Depends(get_satellite_engine),
    request_id: str = Depends(get_request_id),
) -> ConstellationListResponse:
    """Get information about available constellations.

    Args:
        request: FastAPI request object.
        redis: Redis connection.
        satellite_engine: Satellite engine instance.
        request_id: Request ID for tracing.

    Returns:
        ConstellationListResponse: List of constellation information.

    Raises:
        HTTPException: If query fails.
    """
    start_time = time.time()

    logger.info(f"[{request_id}] Getting constellation information")

    try:
        # Check cache
        cache_key = "constellations:all"
        cached_result = None
        try:
            cached_result = await redis.get(cache_key)
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation cache read unavailable: %s", request_id, cache_error
            )

        if cached_result:
            logger.info(f"[{request_id}] Cache hit for constellations")
            result = json.loads(cached_result)
            return ConstellationListResponse(**result)

        # Get constellation data from engine
        constellation_data = await asyncio.wait_for(
            satellite_engine.get_constellations(),
            timeout=settings.satellite_timeout_seconds,
        )

        # Convert to response model
        constellations = []
        for const in constellation_data if isinstance(constellation_data, list) else []:
            if not isinstance(const, dict):
                continue
            constellations.append(
                ConstellationInfo(
                    name=const.get("name", "Unknown"),
                    operator=const.get("operator"),
                    total_satellites=const.get("total_satellites", 0),
                    active_satellites=const.get("active_satellites", 0),
                    orbital_planes=const.get("orbital_planes"),
                    altitude_km=const.get("altitude_km"),
                    inclination_deg=const.get("inclination_deg"),
                )
            )

        response = ConstellationListResponse(
            constellations=constellations,
            total_count=len(constellations),
        )

        # Cache result (longer TTL for constellation info)
        try:
            await redis.setex(
                cache_key,
                3600,  # 1 hour TTL
                json.dumps(response.model_dump(mode="json")),
            )
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation cache write unavailable: %s",
                request_id,
                cache_error,
            )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[{request_id}] Retrieved {len(constellations)} constellations "
            f"in {elapsed_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except asyncio.TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Constellation query timed out",
        ) from e
    except Exception as e:
        logger.error(f"[{request_id}] Failed to get constellations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve constellations: {str(e)}",
        )


# ============================================================================
# Single Constellation Endpoint
# ============================================================================


@router.get(
    "/constellation/{name}",
    response_model=ConstellationInfo,
    responses={
        200: {"description": "Constellation info retrieved successfully"},
        404: {"model": ProblemDetail, "description": "Constellation not found"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Get specific constellation information",
    description="""
    Returns detailed information about a specific satellite constellation.
    
    The constellation name is case-insensitive.
    """,
)
async def get_constellation(
    request: Request,
    name: str,
    redis: Any = Depends(get_redis),
    satellite_engine: Any = Depends(get_satellite_engine),
    request_id: str = Depends(get_request_id),
) -> ConstellationInfo:
    """Get information about a specific constellation.

    Args:
        request: FastAPI request object.
        name: Constellation name.
        redis: Redis connection.
        satellite_engine: Satellite engine instance.
        request_id: Request ID for tracing.

    Returns:
        ConstellationInfo: Constellation details.

    Raises:
        HTTPException: If constellation not found or query fails.
    """
    logger.info(f"[{request_id}] Getting constellation: {name}")

    try:
        # Check cache
        cache_key = f"constellation:{name.lower()}"
        cached_result = None
        try:
            cached_result = await redis.get(cache_key)
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation cache read unavailable: %s", request_id, cache_error
            )

        if cached_result:
            logger.info(f"[{request_id}] Cache hit for constellation {name}")
            return ConstellationInfo(**json.loads(cached_result))

        all_constellations = await asyncio.wait_for(
            satellite_engine.get_constellations(),
            timeout=settings.satellite_timeout_seconds,
        )
        by_name = {
            str(const.get("name", "")).lower(): const
            for const in all_constellations
            if isinstance(const, dict)
        }
        constellation = by_name.get(name.lower())

        if not constellation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Constellation '{name}' not found",
            )

        response = ConstellationInfo(
            name=constellation.get("name", "Unknown"),
            operator=constellation.get("operator"),
            total_satellites=constellation.get("total_satellites", 0),
            active_satellites=constellation.get("active_satellites", 0),
            orbital_planes=constellation.get("orbital_planes"),
            altitude_km=constellation.get("altitude_km"),
            inclination_deg=constellation.get("inclination_deg"),
        )

        # Cache result
        try:
            await redis.setex(
                cache_key,
                3600,  # 1 hour TTL
                json.dumps(response.model_dump(mode="json")),
            )
        except Exception as cache_error:
            logger.warning(
                "[%s] Constellation cache write unavailable: %s",
                request_id,
                cache_error,
            )

        logger.info(f"[{request_id}] Retrieved constellation: {name}")

        return response

    except HTTPException:
        raise
    except asyncio.TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Timed out while retrieving constellation '{name}'",
        ) from e
    except Exception as e:
        logger.error(f"[{request_id}] Failed to get constellation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve constellation: {str(e)}",
        )
