# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Satellite endpoints for querying visible satellites and constellation info.

"""Satellite API endpoints for LinkSpot."""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from config import settings
from dependencies import get_redis, get_request_id, get_satellite_engine
from models.schemas import (
    ConstellationInfo,
    ConstellationListResponse,
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
            logger.warning("[%s] Satellite cache read unavailable: %s", request_id, cache_error)

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
                        azimuth=round(sat_azimuth % 360.0, 2),
                        elevation=round(sat_elevation, 2),
                        range_km=sat.get("range_km"),
                        velocity_kms=sat.get("velocity_kms"),
                        constellation=sat.get("constellation"),
                    )
                )
            except Exception:
                malformed_records += 1

        # Sort by elevation (highest first) and apply deterministic truncation.
        satellites.sort(key=lambda s: (s.elevation, s.satellite_id), reverse=True)
        if len(satellites) > settings.max_satellites_per_query:
            satellites = satellites[:settings.max_satellites_per_query]
            logger.warning(
                "[%s] Truncated results to %d records",
                request_id,
                settings.max_satellites_per_query,
            )
        if malformed_records:
            logger.warning("[%s] Skipped %d malformed satellite records", request_id, malformed_records)

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
            logger.warning("[%s] Satellite cache write unavailable: %s", request_id, cache_error)

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
            logger.warning("[%s] Constellation cache read unavailable: %s", request_id, cache_error)
        
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
            logger.warning("[%s] Constellation cache write unavailable: %s", request_id, cache_error)
        
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
            logger.warning("[%s] Constellation cache read unavailable: %s", request_id, cache_error)
        
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
            logger.warning("[%s] Constellation cache write unavailable: %s", request_id, cache_error)
        
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
