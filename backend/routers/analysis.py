# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Analysis endpoints for satellite visibility and coverage analysis.

"""Analysis API endpoints for LinkSpot."""

import asyncio
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from config import settings
from dependencies import (
    get_amenity_service,
    get_data_pipeline,
    get_obstruction_engine,
    get_redis,
    get_request_id,
    get_satellite_engine,
)
from models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DataQuality,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    HeatmapRequest,
    HeatmapResponse,
    ObstructionPoint,
    ProblemDetail,
    SatelliteDetail,
    VisibilitySummary,
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


def _zone_to_status(zone: Zone) -> str:
    """Map backend Zone enum to frontend status string."""
    if zone in (Zone.EXCELLENT, Zone.GOOD):
        return "clear"
    if zone == Zone.FAIR:
        return "marginal"
    return "dead"


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

    # Calculate number of steps with hard upper bound.
    n_steps = int(radius_m / spacing_m)
    n_steps = min(n_steps, 150)

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


def _point_in_polygon_xy(
    px: float, py: float, polygon: list[tuple[float, float]]
) -> bool:
    inside = False
    n = len(polygon)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / max(yj - yi, 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _distance_to_segment_m(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    seg_x = bx - ax
    seg_y = by - ay
    seg_len_sq = seg_x * seg_x + seg_y * seg_y
    if seg_len_sq <= 1e-9:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * seg_x + (py - ay) * seg_y) / seg_len_sq
    t = max(0.0, min(1.0, t))
    proj_x = ax + t * seg_x
    proj_y = ay + t * seg_y
    return math.hypot(px - proj_x, py - proj_y)


def _filter_driveable_grid_points(
    points: list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
    access_mask: dict[str, Any],
    road_buffer_m: float = 18.0,
    parking_buffer_m: float = 35.0,
) -> list[tuple[float, float]]:
    if not points:
        return []

    roads = access_mask.get("roads", []) if isinstance(access_mask, dict) else []
    parking_polygons = (
        access_mask.get("parking_polygons", []) if isinstance(access_mask, dict) else []
    )
    parking_points = (
        access_mask.get("parking_points", []) if isinstance(access_mask, dict) else []
    )
    if not roads and not parking_polygons and not parking_points:
        return []

    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = max(
        1e-6, meters_per_deg_lat * math.cos(math.radians(center_lat))
    )

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        x = (lon - center_lon) * meters_per_deg_lon
        y = (lat - center_lat) * meters_per_deg_lat
        return x, y

    cell_size = 120.0

    def cell_id(x: float, y: float) -> tuple[int, int]:
        return int(math.floor(x / cell_size)), int(math.floor(y / cell_size))

    road_segments: list[
        tuple[float, float, float, float, float, float, float, float]
    ] = []
    road_cells: dict[tuple[int, int], list[int]] = {}

    for road in roads:
        if not isinstance(road, list) or len(road) < 2:
            continue
        coords = []
        for coord in road:
            if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                continue
            lat = float(coord[0])
            lon = float(coord[1])
            coords.append(to_xy(lat, lon))
        if len(coords) < 2:
            continue

        for idx in range(1, len(coords)):
            ax, ay = coords[idx - 1]
            bx, by = coords[idx]
            min_x = min(ax, bx) - road_buffer_m
            max_x = max(ax, bx) + road_buffer_m
            min_y = min(ay, by) - road_buffer_m
            max_y = max(ay, by) + road_buffer_m
            segment_index = len(road_segments)
            road_segments.append((ax, ay, bx, by, min_x, max_x, min_y, max_y))
            min_cx = int(math.floor(min_x / cell_size))
            max_cx = int(math.floor(max_x / cell_size))
            min_cy = int(math.floor(min_y / cell_size))
            max_cy = int(math.floor(max_y / cell_size))
            for cx in range(min_cx, max_cx + 1):
                for cy in range(min_cy, max_cy + 1):
                    road_cells.setdefault((cx, cy), []).append(segment_index)

    polygon_items: list[
        tuple[list[tuple[float, float]], tuple[float, float, float, float]]
    ] = []
    polygon_cells: dict[tuple[int, int], list[int]] = {}

    for polygon in parking_polygons:
        if not isinstance(polygon, list) or len(polygon) < 3:
            continue
        vertices: list[tuple[float, float]] = []
        for coord in polygon:
            if not isinstance(coord, (list, tuple)) or len(coord) < 2:
                continue
            lat = float(coord[0])
            lon = float(coord[1])
            vertices.append(to_xy(lat, lon))
        if len(vertices) < 3:
            continue

        xs = [point[0] for point in vertices]
        ys = [point[1] for point in vertices]
        bounds = (min(xs), max(xs), min(ys), max(ys))
        polygon_index = len(polygon_items)
        polygon_items.append((vertices, bounds))

        min_cx = int(math.floor(bounds[0] / cell_size))
        max_cx = int(math.floor(bounds[1] / cell_size))
        min_cy = int(math.floor(bounds[2] / cell_size))
        max_cy = int(math.floor(bounds[3] / cell_size))
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                polygon_cells.setdefault((cx, cy), []).append(polygon_index)

    parking_xy: list[tuple[float, float]] = []
    parking_cells: dict[tuple[int, int], list[int]] = {}
    for coord in parking_points:
        if not isinstance(coord, (list, tuple)) or len(coord) < 2:
            continue
        lat = float(coord[0])
        lon = float(coord[1])
        x, y = to_xy(lat, lon)
        idx = len(parking_xy)
        parking_xy.append((x, y))
        cx, cy = cell_id(x, y)
        parking_cells.setdefault((cx, cy), []).append(idx)

    def nearby_cells(x: float, y: float, radius_m: float) -> list[tuple[int, int]]:
        cx, cy = cell_id(x, y)
        delta = max(1, int(math.ceil(radius_m / cell_size)))
        cells = []
        for ix in range(cx - delta, cx + delta + 1):
            for iy in range(cy - delta, cy + delta + 1):
                cells.append((ix, iy))
        return cells

    filtered: list[tuple[float, float]] = []
    for lat, lon in points:
        x, y = to_xy(lat, lon)

        matched = False
        for key in nearby_cells(x, y, parking_buffer_m):
            for idx in parking_cells.get(key, []):
                px, py = parking_xy[idx]
                if math.hypot(x - px, y - py) <= parking_buffer_m:
                    matched = True
                    break
            if matched:
                break

        if not matched:
            for key in nearby_cells(x, y, 0.0):
                for idx in polygon_cells.get(key, []):
                    vertices, bounds = polygon_items[idx]
                    if x < bounds[0] or x > bounds[1] or y < bounds[2] or y > bounds[3]:
                        continue
                    if _point_in_polygon_xy(x, y, vertices):
                        matched = True
                        break
                if matched:
                    break

        if not matched:
            for key in nearby_cells(x, y, road_buffer_m):
                for idx in road_cells.get(key, []):
                    ax, ay, bx, by, min_x, max_x, min_y, max_y = road_segments[idx]
                    if x < min_x or x > max_x or y < min_y or y > max_y:
                        continue
                    if _distance_to_segment_m(x, y, ax, ay, bx, by) <= road_buffer_m:
                        matched = True
                        break
                if matched:
                    break

        if matched:
            filtered.append((lat, lon))

    return filtered


def _normalize_bool(
    record: dict[str, Any], primary: str, fallback: str, default: bool
) -> bool:
    """Normalize bool flags across legacy payload variants."""
    value = record.get(primary)
    if value is None:
        value = record.get(fallback, default)
    return bool(value)


def _normalize_obstruction_result(raw: Any) -> dict[str, Any]:
    """Validate and normalize obstruction-engine payload."""
    if not isinstance(raw, dict):
        return {
            "n_clear": 0,
            "n_total": 0,
            "obstruction_pct": 100.0,
            "blocked_azimuths": [],
            "satellite_details": [],
            "obstruction_profile": [],
        }

    n_clear = int(raw.get("n_clear", 0) or 0)
    n_total = int(raw.get("n_total", 0) or 0)
    if n_total < 0:
        n_total = 0
    if n_clear < 0:
        n_clear = 0
    if n_clear > n_total and n_total > 0:
        n_clear = n_total

    return {
        "n_clear": n_clear,
        "n_total": n_total,
        "obstruction_pct": min(
            100.0, max(0.0, float(raw.get("obstruction_pct", 0.0) or 0.0))
        ),
        "blocked_azimuths": list(raw.get("blocked_azimuths", []) or []),
        "satellite_details": list(raw.get("satellite_details", []) or []),
        "obstruction_profile": list(raw.get("obstruction_profile", []) or []),
    }


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
    redis: Any = Depends(get_redis),
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
    deadline = start_time + settings.analyze_timeout_seconds
    timestamp = body.timestamp or datetime.now(timezone.utc)
    if not (math.isfinite(body.lat) and math.isfinite(body.lon)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Latitude/longitude must be finite numbers",
        )

    logger.info(f"[{request_id}] Starting analysis for lat={body.lat}, lon={body.lon}")

    try:
        # Check cache first (round timestamp to nearest minute for cache hits)
        cache_ts = timestamp.replace(second=0, microsecond=0)
        cache_params = {
            "lat": round(body.lat, 6),
            "lon": round(body.lon, 6),
            "elevation": body.elevation,
            "timestamp": cache_ts.isoformat(),
            "timeout_s": settings.analyze_timeout_seconds,
        }
        cache_key = _generate_cache_key("analyze", cache_params)

        cached_result = await redis.get(cache_key)
        if cached_result:
            logger.info(f"[{request_id}] Cache hit for analysis")
            result = json.loads(cached_result)
            return AnalyzeResponse(**result)
        logger.debug("[%s] Analyze cache miss", request_id)

        # Step 1: Get visible satellites
        satellites = await asyncio.wait_for(
            satellite_engine.get_visible_satellites(
                lat=body.lat,
                lon=body.lon,
                elevation=body.elevation,
                timestamp=timestamp,
            ),
            timeout=settings.satellite_timeout_seconds,
        )

        n_total = len(satellites)
        logger.debug(f"[{request_id}] Found {n_total} visible satellites")

        # Step 2: Fetch building and terrain data
        buildings_result = await data_pipeline.fetch_buildings(
            lat=body.lat,
            lon=body.lon,
            radius_m=1000.0,  # 1km radius for buildings
        )
        if isinstance(buildings_result, tuple):
            buildings, building_source = buildings_result
        else:
            buildings = buildings_result or []
            building_source = "unknown"

        terrain = await data_pipeline.fetch_terrain(
            lat=body.lat,
            lon=body.lon,
            radius_m=5000.0,  # 5km radius for terrain
        )
        if time.time() > deadline:
            raise asyncio.TimeoutError(
                "analyze deadline exceeded before obstruction stage"
            )
        if not isinstance(buildings, list):
            buildings = []
        if not isinstance(terrain, list):
            terrain = []

        logger.debug(
            f"[{request_id}] Fetched {len(buildings)} buildings, "
            f"{len(terrain)} terrain samples"
        )

        # Step 3: Perform obstruction analysis
        obstruction_raw = obstruction_engine.analyze_position(
            lat=body.lat,
            lon=body.lon,
            elevation=body.elevation,
            buildings=buildings,
            terrain=terrain,
            satellites=satellites,
        )
        obstruction_result = _normalize_obstruction_result(obstruction_raw)

        n_clear = obstruction_result["n_clear"]
        n_total_calc = obstruction_result.get("n_total", n_total)
        obstruction_pct = obstruction_result["obstruction_pct"]
        blocked_azimuths = obstruction_result["blocked_azimuths"]

        # Build data-quality metadata for transparency
        dq_sources = ["satellites"]
        dq_warnings = []

        if buildings:
            building_quality = "full"
            if building_source and building_source not in ("unknown", "none"):
                dq_sources.append(f"buildings:{building_source}")
            else:
                dq_sources.append("buildings")
        else:
            building_quality = "none"
            dq_warnings.append(
                "No building data available - obstruction analysis may be inaccurate"
            )

        terrain_source = next(
            (
                t.get("source")
                for t in terrain
                if isinstance(t, dict) and t.get("source")
            ),
            None,
        )
        if terrain:
            terrain_quality = "full"
            dq_sources.append(
                f"terrain:{terrain_source}" if terrain_source else "terrain"
            )
        else:
            terrain_quality = "none"
            dq_warnings.append("Terrain elevation data unavailable")

        data_quality = DataQuality(
            buildings=building_quality,
            terrain=terrain_quality,
            satellites="live",
            sources=dq_sources,
            warnings=dq_warnings,
        )

        # Extract per-satellite details and obstruction profile
        sat_details = obstruction_result.get("satellite_details", [])
        obstruction_profile = obstruction_result.get("obstruction_profile", [])

        satellites_out = [
            SatelliteDetail(
                id=str(sd.get("satellite_id") or sd.get("id") or "UNKNOWN"),
                name=sd.get("name", ""),
                azimuth=sd["azimuth"],
                elevation=sd["elevation"],
                range_km=sd.get("range_km"),
                visible=_normalize_bool(sd, "visible", "is_visible", True),
                obstructed=_normalize_bool(sd, "obstructed", "is_obstructed", False),
            )
            for sd in sat_details
            if isinstance(sd, dict)
            and ("satellite_id" in sd or "id" in sd)
            and "azimuth" in sd
            and "elevation" in sd
        ]

        obstructions_out = [
            ObstructionPoint(azimuth=op["azimuth"], elevation=op["elevation"])
            for op in obstruction_profile
            if isinstance(op, dict) and "azimuth" in op and "elevation" in op
        ]

        n_obstructed = sum(1 for s in satellites_out if s.obstructed)
        visibility = VisibilitySummary(
            visible_satellites=n_clear,
            obstructed_satellites=n_obstructed,
            total_satellites=n_total_calc,
        )

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
            visibility=visibility,
            satellites=satellites_out,
            obstructions=obstructions_out,
            data_quality=data_quality,
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
    except asyncio.TimeoutError as e:
        logger.warning(f"[{request_id}] Analysis timed out [timeout]: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Analysis timed out",
        ) from e
    except Exception as e:
        message = str(e).lower()
        category = "internal_error"
        if "connection" in message or "timeout" in message:
            category = "upstream_unavailable"
        elif "validation" in message:
            category = "validation"
        logger.error(f"[{request_id}] Analysis failed [{category}]: {e}", exc_info=True)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if category == "upstream_unavailable"
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
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
    redis: Any = Depends(get_redis),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
    amenity_service: Any = Depends(get_amenity_service),
    request_id: str = Depends(get_request_id),
) -> HeatmapResponse:
    """Generate coverage heatmap for an area.

    Args:
        request: FastAPI request object.
        body: Heatmap request parameters.
        redis: Redis connection.
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
        # Check cache first (round timestamp to nearest minute for cache hits)
        cache_ts = timestamp.replace(second=0, microsecond=0)
        cache_params = {
            "lat": round(body.lat, 6),
            "lon": round(body.lon, 6),
            "radius_m": body.radius_m,
            "spacing_m": body.spacing_m,
            "timestamp": cache_ts.isoformat(),
            "timeout_s": settings.heatmap_timeout_seconds,
            "driveable_only": True,
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
        deadline = start_time + settings.heatmap_timeout_seconds

        road_mask_applied = False
        road_mask_warnings: list[str] = []
        accessible_points: list[tuple[float, float]] = []

        lat_delta = body.radius_m / 111000.0 + 0.002
        lon_delta = lat_delta / max(math.cos(math.radians(body.lat)), 1e-6)
        min_lat = body.lat - lat_delta
        max_lat = body.lat + lat_delta
        min_lon = body.lon - lon_delta
        max_lon = body.lon + lon_delta

        try:
            access_mask = await asyncio.wait_for(
                asyncio.to_thread(
                    amenity_service.query_road_access_mask,
                    min_lat,
                    min_lon,
                    max_lat,
                    max_lon,
                ),
                timeout=min(12.0, settings.heatmap_timeout_seconds),
            )
            if isinstance(access_mask, dict) and (
                access_mask.get("roads")
                or access_mask.get("parking_polygons")
                or access_mask.get("parking_points")
            ):
                road_mask_applied = True
                accessible_points = _filter_driveable_grid_points(
                    points=grid_points,
                    center_lat=body.lat,
                    center_lon=body.lon,
                    access_mask=access_mask,
                    road_buffer_m=settings.heatmap_road_mask_buffer_meters,
                    parking_buffer_m=settings.heatmap_parking_mask_buffer_meters,
                )
                if not accessible_points:
                    road_mask_warnings.append(
                        "Road/parking mask removed all off-road cells for this area"
                    )
            else:
                road_mask_warnings.append(
                    "Road/parking mask unavailable - suppressing off-road recommendations"
                )
        except Exception as exc:
            logger.warning("[%s] Road mask lookup failed: %s", request_id, exc)
            road_mask_warnings.append(
                "Road/parking mask lookup failed - suppressing off-road recommendations"
            )

        if not road_mask_applied:
            accessible_points = list(grid_points)

        logger.info(
            f"[{request_id}] Analyzing {len(accessible_points)} heatmap grid points"
        )

        # Fetch buildings and terrain for the entire area
        buildings_result = await data_pipeline.fetch_buildings(
            lat=body.lat,
            lon=body.lon,
            radius_m=body.radius_m + 500.0,  # Extra margin
        )
        if isinstance(buildings_result, tuple):
            buildings, building_source = buildings_result
        else:
            buildings = buildings_result or []
            building_source = "unknown"

        terrain = await data_pipeline.fetch_terrain(
            lat=body.lat,
            lon=body.lon,
            radius_m=body.radius_m + 1000.0,  # Extra margin
        )
        if not isinstance(terrain, list):
            terrain = []
        if not terrain:
            logger.warning(
                "[%s] Terrain unavailable for heatmap, continuing in degraded mode",
                request_id,
            )

        # Get all satellites for the area
        satellites = await asyncio.wait_for(
            satellite_engine.get_visible_satellites(
                lat=body.lat,
                lon=body.lon,
                elevation=0.0,
                timestamp=timestamp,
            ),
            timeout=settings.satellite_timeout_seconds,
        )

        # Build data-quality metadata for transparency
        dq_sources = ["satellites"]
        dq_warnings = list(road_mask_warnings)
        if road_mask_applied:
            dq_sources.append("roads:overpass")
        if buildings:
            building_quality = "full"
            if building_source and building_source not in ("unknown", "none"):
                dq_sources.append(f"buildings:{building_source}")
            else:
                dq_sources.append("buildings")
        else:
            building_quality = "none"
            dq_warnings.append(
                "No building data available - obstruction analysis may be inaccurate"
            )

        terrain_source = next(
            (
                t.get("source")
                for t in terrain
                if isinstance(t, dict) and t.get("source")
            ),
            None,
        )
        if terrain:
            terrain_quality = "full"
            dq_sources.append(
                f"terrain:{terrain_source}" if terrain_source else "terrain"
            )
        else:
            terrain_quality = "none"
            dq_warnings.append("Terrain elevation data unavailable")

        data_quality = DataQuality(
            buildings=building_quality,
            terrain=terrain_quality,
            satellites="live",
            sources=dq_sources,
            warnings=dq_warnings,
        )

        # Precompute half-cell sizes for polygon generation
        half_lat = (body.spacing_m / 111000.0) / 2

        # Analyze each grid point
        features = []
        for idx, (lat, lon) in enumerate(accessible_points):
            if time.time() > deadline:
                logger.warning(
                    "[%s] Heatmap budget exceeded at point %d/%d",
                    request_id,
                    idx,
                    len(accessible_points),
                )
                break
            if idx and idx % 64 == 0:
                await asyncio.sleep(0)
            # Analyze position
            obstruction_raw = obstruction_engine.analyze_position(
                lat=lat,
                lon=lon,
                elevation=0.0,
                buildings=buildings,
                terrain=terrain,
                satellites=satellites,
            )
            obstruction_result = _normalize_obstruction_result(obstruction_raw)

            n_clear = obstruction_result["n_clear"]
            n_total = obstruction_result["n_total"]
            obstruction_pct = obstruction_result["obstruction_pct"]

            clear_ratio = n_clear / n_total if n_total > 0 else 0.0
            zone = _classify_zone(clear_ratio)

            # Build polygon cell (square) around grid point
            half_lon = half_lat / max(math.cos(math.radians(lat)), 1e-10)
            polygon_coords = [
                [
                    [lon - half_lon, lat - half_lat],
                    [lon + half_lon, lat - half_lat],
                    [lon + half_lon, lat + half_lat],
                    [lon - half_lon, lat + half_lat],
                    [lon - half_lon, lat - half_lat],
                ]
            ]

            # Create GeoJSON feature with frontend-expected properties
            feature = GeoJSONFeature(
                id=idx,
                geometry=GeoJSONGeometry(
                    type="Polygon",
                    coordinates=polygon_coords,
                ),
                properties={
                    "status": _zone_to_status(zone),
                    "visible_count": n_clear,
                    "center": {"lat": lat, "lon": lon},
                    "zone": zone.value,
                    "n_clear": n_clear,
                    "n_total": n_total,
                    "obstruction_pct": round(obstruction_pct, 2),
                    "clear_ratio": round(clear_ratio, 3),
                },
            )
            features.append(feature)

        # Convert buildings to GeoJSON features
        building_features = []
        for bidx, bldg in enumerate(buildings):
            geom = bldg.get("geometry")
            if geom:
                try:
                    building_features.append(
                        GeoJSONFeature(
                            id=f"b{bidx}",
                            geometry=GeoJSONGeometry(**geom),
                            properties={
                                "height": bldg.get("height", 0),
                            },
                        )
                    )
                except Exception:
                    continue

        # Build response matching frontend expectations
        response = HeatmapResponse(
            grid=GeoJSONFeatureCollection(features=features),
            buildings=GeoJSONFeatureCollection(features=building_features),
            center={"lat": body.lat, "lon": body.lon},
            radius=body.radius_m,
            resolution=body.spacing_m,
            timestamp=timestamp.isoformat(),
            data_quality=data_quality,
        )

        # Cache result (longer TTL for heatmaps)
        await redis.setex(
            cache_key,
            settings.cache_ttl_seconds * 2,
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
    except asyncio.TimeoutError as e:
        logger.warning(f"[{request_id}] Heatmap generation timed out [timeout]: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Heatmap generation timed out",
        ) from e
    except Exception as e:
        message = str(e).lower()
        category = "internal_error"
        if "connection" in message or "timeout" in message:
            category = "upstream_unavailable"
        logger.error(
            f"[{request_id}] Heatmap generation failed [{category}]: {e}", exc_info=True
        )
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if category == "upstream_unavailable"
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"Heatmap generation failed: {str(e)}",
        )
