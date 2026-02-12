# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Analysis endpoints for satellite visibility and coverage analysis.

"""Analysis API endpoints for LinkSpot."""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aioredis
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from config import settings
from dependencies import (
    get_data_pipeline,
    get_db,
    get_obstruction_engine,
    get_redis,
    get_request_id,
    get_satellite_engine,
)
from models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    HeatmapRequest,
    HeatmapResponse,
    ProblemDetail,
    Zone,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v1", tags=["Analysis"])


# ============================================================================
# Helper Functions
# ============================================================================

def _generate_cache_key(prefix: str, params: dict) -> str:
    """Generate cache key from parameters.
    
    Args:
        prefix: Cache key prefix.
        params: Parameters to hash.
        
    Returns:
        str: Cache key.
    """
    # Normalize params for consistent hashing
    normalized = json.dumps(params, sort_keys=True, default=str)
    hash_value = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"{prefix}:{hash_value}"


def _classify_zone(clear_ratio: float) -> Zone:
    """Classify coverage zone based on clear satellite ratio.
    
    Args:
        clear_ratio: Ratio of clear satellites (0.0 to 1.0).
        
    Returns:
        Zone: Zone classification.
    """
    if clear_ratio >= settings.zone_excellent_threshold:
        return Zone.EXCELLENT
    elif clear_ratio >= settings.zone_good_threshold:
        return Zone.GOOD
    elif clear_ratio >= settings.zone_fair_threshold:
        return Zone.FAIR
    elif clear_ratio > 0.0:
        return Zone.POOR
    return Zone.BLOCKED


def _generate_grid_points(
    center_lat: float,
    center_lon: float,
    radius_m: int,
    spacing_m: int,
) -> list[tuple[float, float]]:
    """Generate grid points for heatmap analysis.
    
    Args:
        center_lat: Center latitude.
        center_lon: Center longitude.
        radius_m: Radius in meters.
        spacing_m: Grid spacing in meters.
        
    Returns:
        list: List of (lat, lon) tuples.
    """
    import math
    
    points = []
    
    # Convert spacing to approximate degrees (rough approximation)
    # 1 degree latitude ≈ 111 km
    lat_spacing = spacing_m / 111000.0
    
    # Calculate number of steps
    n_steps = int(radius_m / spacing_m)
    
    for i in range(-n_steps, n_steps + 1):
        for j in range(-n_steps, n_steps + 1):
            lat = center_lat + (i * lat_spacing)
            
            # Longitude spacing varies with latitude
            lon_spacing = lat_spacing / math.cos(math.radians(lat))
            lon = center_lon + (j * lon_spacing)
            
            # Check if point is within radius
            dx = (lon - center_lon) * 111000.0 * math.cos(math.radians(center_lat))
            dy = (lat - center_lat) * 111000.0
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance <= radius_m:
                points.append((lat, lon))
    
    return points


# ============================================================================
# Single Position Analysis Endpoint
# ============================================================================

@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    responses={
        200: {"description": "Analysis completed successfully"},
        400: {"model": ProblemDetail, "description": "Invalid request parameters"},
        422: {"model": ProblemDetail, "description": "Validation error"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Analyze satellite visibility at a single position",
    description="""
    Performs comprehensive satellite visibility analysis at a specific geographic location.
    
    The analysis includes:
    - Satellite positions and visibility
    - Building/terrain obstruction detection
    - Coverage zone classification
    - Blocked azimuth ranges
    
    Results are cached for improved performance on repeated queries.
    """,
)
async def analyze_position(
    request: Request,
    body: AnalyzeRequest,
    redis: aioredis.Redis = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
    request_id: str = Depends(get_request_id),
) -> AnalyzeResponse:
    """Analyze satellite visibility at a single position.
    
    Args:
        request: FastAPI request object.
        body: Analysis request parameters.
        redis: Redis connection.
        db: Database connection.
        satellite_engine: Satellite engine instance.
        data_pipeline: Data pipeline instance.
        obstruction_engine: Obstruction engine instance.
        request_id: Request ID for tracing.
        
    Returns:
        AnalyzeResponse: Analysis results.
        
    Raises:
        HTTPException: If analysis fails.
    """
    start_time = time.time()
    timestamp = body.timestamp or datetime.now(timezone.utc)
    
    logger.info(
        f"[{request_id}] Starting analysis for lat={body.lat}, lon={body.lon}"
    )
    
    try:
        # Check cache first
        cache_params = {
            "lat": round(body.lat, 6),
            "lon": round(body.lon, 6),
            "elevation": body.elevation,
            "timestamp": timestamp.isoformat(),
        }
        cache_key = _generate_cache_key("analyze", cache_params)
        
        cached_result = await redis.get(cache_key)
        if cached_result:
            logger.info(f"[{request_id}] Cache hit for analysis")
            result = json.loads(cached_result)
            return AnalyzeResponse(**result)
        
        # Step 1: Get visible satellites
        satellites = await satellite_engine.get_visible_satellites(
            lat=body.lat,
            lon=body.lon,
            elevation=body.elevation,
            timestamp=timestamp,
        )
        
        n_total = len(satellites)
        logger.debug(f"[{request_id}] Found {n_total} visible satellites")
        
        # Step 2: Fetch building and terrain data
        buildings = await data_pipeline.fetch_buildings(
            lat=body.lat,
            lon=body.lon,
            radius_m=1000.0,  # 1km radius for buildings
        )
        
        terrain = await data_pipeline.fetch_terrain(
            lat=body.lat,
            lon=body.lon,
            radius_m=5000.0,  # 5km radius for terrain
        )
        
        logger.debug(
            f"[{request_id}] Fetched {len(buildings)} buildings, "
            f"{len(terrain)} terrain samples"
        )
        
        # Step 3: Perform obstruction analysis
        obstruction_result = obstruction_engine.analyze_position(
            lat=body.lat,
            lon=body.lon,
            elevation=body.elevation,
            buildings=buildings,
            terrain=terrain,
            satellites=satellites,
        )
        
        n_clear = obstruction_result["n_clear"]
        n_total_calc = obstruction_result.get("n_total", n_total)
        obstruction_pct = obstruction_result["obstruction_pct"]
        blocked_azimuths = obstruction_result["blocked_azimuths"]
        
        # Calculate clear ratio and zone
        clear_ratio = n_clear / n_total_calc if n_total_calc > 0 else 0.0
        zone = _classify_zone(clear_ratio)
        
        # Build response
        response = AnalyzeResponse(
            zone=zone,
            n_clear=n_clear,
            n_total=n_total_calc,
            obstruction_pct=obstruction_pct,
            blocked_azimuths=blocked_azimuths,
            timestamp=timestamp,
            lat=body.lat,
            lon=body.lon,
            elevation=body.elevation,
        )
        
        # Cache result
        await redis.setex(
            cache_key,
            settings.cache_ttl_seconds,
            json.dumps(response.model_dump(mode="json")),
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[{request_id}] Analysis completed in {elapsed_ms:.1f}ms: "
            f"zone={zone.value}, n_clear={n_clear}/{n_total_calc}"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{request_id}] Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}",
        )


# ============================================================================
# Heatmap Analysis Endpoint
# ============================================================================

@router.post(
    "/heatmap",
    response_model=HeatmapResponse,
    responses={
        200: {"description": "Heatmap generated successfully"},
        400: {"model": ProblemDetail, "description": "Invalid request parameters"},
        422: {"model": ProblemDetail, "description": "Validation error"},
        429: {"model": ProblemDetail, "description": "Rate limit exceeded"},
        503: {"model": ProblemDetail, "description": "Service unavailable"},
    },
    summary="Generate coverage heatmap for an area",
    description="""
    Generates a satellite coverage heatmap for a geographic area.
    
    The heatmap is created by:
    1. Generating a grid of points within the specified radius
    2. Analyzing satellite visibility at each grid point
    3. Classifying each point into a coverage zone
    4. Returning results as a GeoJSON FeatureCollection
    
    **Performance Targets:**
    - Cold cache: < 5 seconds
    - Warm cache: < 2 seconds
    - 99th percentile: < 8 seconds
    
    **Limits:**
    - Maximum radius: 10 km
    - Maximum points: 10,000
    """,
)
async def generate_heatmap(
    request: Request,
    body: HeatmapRequest,
    redis: aioredis.Redis = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
    request_id: str = Depends(get_request_id),
) -> HeatmapResponse:
    """Generate coverage heatmap for an area.
    
    Args:
        request: FastAPI request object.
        body: Heatmap request parameters.
        redis: Redis connection.
        db: Database connection.
        satellite_engine: Satellite engine instance.
        data_pipeline: Data pipeline instance.
        obstruction_engine: Obstruction engine instance.
        request_id: Request ID for tracing.
        
    Returns:
        HeatmapResponse: GeoJSON FeatureCollection with coverage data.
        
    Raises:
        HTTPException: If heatmap generation fails.
    """
    start_time = time.time()
    timestamp = body.timestamp or datetime.now(timezone.utc)
    
    logger.info(
        f"[{request_id}] Starting heatmap generation: "
        f"center=({body.lat}, {body.lon}), radius={body.radius_m}m, "
        f"spacing={body.spacing_m}m"
    )
    
    try:
        # Check cache first
        cache_params = {
            "lat": round(body.lat, 6),
            "lon": round(body.lon, 6),
            "radius_m": body.radius_m,
            "spacing_m": body.spacing_m,
            "timestamp": timestamp.isoformat(),
        }
        cache_key = _generate_cache_key("heatmap", cache_params)
        
        cached_result = await redis.get(cache_key)
        if cached_result:
            logger.info(f"[{request_id}] Cache hit for heatmap")
            result = json.loads(cached_result)
            return HeatmapResponse(**result)
        
        # Generate grid points
        grid_points = _generate_grid_points(
            center_lat=body.lat,
            center_lon=body.lon,
            radius_m=body.radius_m,
            spacing_m=body.spacing_m,
        )
        
        # Check point limit
        if len(grid_points) > settings.heatmap_max_points:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Too many grid points ({len(grid_points)}). "
                    f"Maximum is {settings.heatmap_max_points}. "
                    f"Increase spacing or decrease radius."
                ),
            )
        
        logger.info(f"[{request_id}] Analyzing {len(grid_points)} grid points")
        
        # Fetch buildings and terrain for the entire area
        buildings = await data_pipeline.fetch_buildings(
            lat=body.lat,
            lon=body.lon,
            radius_m=body.radius_m + 500.0,  # Extra margin
        )
        
        terrain = await data_pipeline.fetch_terrain(
            lat=body.lat,
            lon=body.lon,
            radius_m=body.radius_m + 1000.0,  # Extra margin
        )
        
        # Get all satellites for the area
        satellites = await satellite_engine.get_visible_satellites(
            lat=body.lat,
            lon=body.lon,
            elevation=0.0,
            timestamp=timestamp,
        )
        
        # Analyze each grid point
        features = []
        for idx, (lat, lon) in enumerate(grid_points):
            # Analyze position
            obstruction_result = obstruction_engine.analyze_position(
                lat=lat,
                lon=lon,
                elevation=0.0,
                buildings=buildings,
                terrain=terrain,
                satellites=satellites,
            )
            
            n_clear = obstruction_result["n_clear"]
            n_total = obstruction_result["n_total"]
            obstruction_pct = obstruction_result["obstruction_pct"]
            
            clear_ratio = n_clear / n_total if n_total > 0 else 0.0
            zone = _classify_zone(clear_ratio)
            
            # Create GeoJSON feature
            feature = GeoJSONFeature(
                id=idx,
                geometry=GeoJSONGeometry(
                    type="Point",
                    coordinates=[lon, lat],
                ),
                properties={
                    "zone": zone.value,
                    "n_clear": n_clear,
                    "n_total": n_total,
                    "obstruction_pct": round(obstruction_pct, 2),
                    "clear_ratio": round(clear_ratio, 3),
                },
            )
            features.append(feature)
        
        # Build response
        response = HeatmapResponse(
            type="FeatureCollection",
            features=features,
            metadata={
                "center_lat": body.lat,
                "center_lon": body.lon,
                "radius_m": body.radius_m,
                "spacing_m": body.spacing_m,
                "total_points": len(grid_points),
                "timestamp": timestamp.isoformat(),
                "generation_time_ms": round((time.time() - start_time) * 1000, 2),
            },
        )
        
        # Cache result (longer TTL for heatmaps)
        await redis.setex(
            cache_key,
            settings.cache_ttl_seconds * 2,  # Double TTL for heatmaps
            json.dumps(response.model_dump(mode="json")),
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[{request_id}] Heatmap generated in {elapsed_ms:.1f}ms: "
            f"{len(grid_points)} points"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{request_id}] Heatmap generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Heatmap generation failed: {str(e)}",
        )
