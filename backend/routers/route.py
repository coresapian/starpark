# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Route planning endpoints for mission-based satellite connectivity analysis.

"""Route planning API endpoints for LinkSpot."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from config import settings
from dependencies import (
    get_amenity_service,
    get_data_pipeline,
    get_obstruction_engine,
    get_osrm_client,
    get_request_id,
    get_satellite_engine,
)
from models.schemas import (
    DataQuality,
    DeadZone,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    MissionSummary,
    RouteLocation,
    RoutePlanRequest,
    RoutePlanResponse,
    Waypoint,
    WaypointAmenities,
    Zone,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Route Planning"])


def _parse_timestamp(value: str | None) -> datetime:
    """Parse request timestamp, defaulting to current UTC."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        # Normalize trailing Z for fromisoformat compatibility.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid time_utc format: {value}",
        ) from e
        # TODO: Return field-level validation detail for malformed timestamps and timezone offsets.


def _classify_zone(clear_ratio: float) -> Zone:
    """Classify route sample zone from clear-satellite ratio."""
    if clear_ratio >= settings.zone_excellent_threshold:
        return Zone.EXCELLENT
    if clear_ratio >= settings.zone_good_threshold:
        return Zone.GOOD
    if clear_ratio >= settings.zone_fair_threshold:
        return Zone.FAIR
    if clear_ratio > 0.0:
        return Zone.POOR
    return Zone.BLOCKED


def _signal_label(zone: Zone) -> str:
    """Map zone to mission signal label."""
    if zone in (Zone.EXCELLENT, Zone.GOOD):
        return "clear"
    if zone == Zone.FAIR:
        return "marginal"
    return "dead"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _resolve_location(
    location: RouteLocation, amenity_service: Any
) -> tuple[float, float]:
    """Resolve a RouteLocation to concrete lat/lon."""
    if location.lat is not None and location.lon is not None:
        return float(location.lat), float(location.lon)

    if not location.address:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Origin/destination must contain coordinates or address",
        )

    try:
        return amenity_service.geocode_address(location.address)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to geocode address: {location.address}",
        ) from e


async def _resolve_location_async(
    location: RouteLocation, amenity_service: Any
) -> tuple[float, float]:
    """Resolve RouteLocation without blocking the event loop."""
    return await asyncio.to_thread(_resolve_location, location, amenity_service)


def _to_local_xy(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
) -> tuple[float, float]:
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = meters_per_deg_lat * math.cos(math.radians(ref_lat))
    x = (lon - ref_lon) * meters_per_deg_lon
    y = (lat - ref_lat) * meters_per_deg_lat
    return x, y


def _distance_to_segment_m(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> tuple[float, float]:
    seg_x = bx - ax
    seg_y = by - ay
    seg_len_sq = seg_x * seg_x + seg_y * seg_y
    if seg_len_sq <= 1e-9:
        dist = math.hypot(px - ax, py - ay)
        return dist, 0.0

    t = ((px - ax) * seg_x + (py - ay) * seg_y) / seg_len_sq
    t = max(0.0, min(1.0, t))
    proj_x = ax + t * seg_x
    proj_y = ay + t * seg_y
    dist = math.hypot(px - proj_x, py - proj_y)
    return dist, t


def _project_to_route(
    lat: float,
    lon: float,
    geometry: list[tuple[float, float]],
) -> tuple[float, float] | None:
    if len(geometry) < 2:
        return None

    ref_lat, ref_lon = geometry[0]
    point_x, point_y = _to_local_xy(lat, lon, ref_lat, ref_lon)

    geometry_xy = [
        _to_local_xy(vertex_lat, vertex_lon, ref_lat, ref_lon)
        for vertex_lat, vertex_lon in geometry
    ]

    best_distance = float("inf")
    best_along = 0.0
    cumulative = 0.0

    for idx in range(1, len(geometry_xy)):
        ax, ay = geometry_xy[idx - 1]
        bx, by = geometry_xy[idx]
        segment_length = math.hypot(bx - ax, by - ay)
        dist, t = _distance_to_segment_m(point_x, point_y, ax, ay, bx, by)
        if dist < best_distance:
            best_distance = dist
            best_along = cumulative + (segment_length * t)
        cumulative += segment_length

    return best_distance, best_along


def _rank_waypoints(candidate_results: list[dict], route: dict) -> list[Waypoint]:
    """Rank and format route-validated parking/fuel/rest candidates."""
    if not candidate_results:
        return []

    avg_speed_mps = (
        route["distance_m"] / route["duration_s"]
        if route.get("duration_s", 0) > 0
        else 20.0
    )

    ordered = sorted(
        candidate_results,
        key=lambda item: (
            -float(item.get("reliability_pct", 0.0)),
            -float(item.get("n_visible", 0)),
            float(item.get("distance_from_route_m", 0.0)),
            float(item.get("distance_along_m", 0.0)),
        ),
    )

    deduped: list[dict] = []
    for candidate in ordered:
        too_close = any(
            abs(candidate["distance_along_m"] - prev["distance_along_m"]) < 200.0
            for prev in deduped
        )
        if too_close:
            continue
        deduped.append(candidate)

    deduped.sort(key=lambda item: item["distance_along_m"])

    waypoints: list[Waypoint] = []
    min_reliability_pct = settings.route_waypoint_min_reliability_pct
    for candidate in deduped:
        if candidate.get("zone") not in (Zone.EXCELLENT, Zone.GOOD):
            continue
        if float(candidate.get("reliability_pct", 0.0)) < min_reliability_pct:
            continue

        n_total = int(candidate.get("n_total", 0))
        n_visible = int(candidate.get("n_visible", 0))
        coverage_pct = (n_visible / n_total * 100.0) if n_total > 0 else 0.0
        eta_seconds = candidate["distance_along_m"] / avg_speed_mps
        waypoint_index = len(waypoints) + 1

        waypoints.append(
            Waypoint(
                id=f"WP-{waypoint_index:02d}",
                lat=float(candidate["lat"]),
                lon=float(candidate["lon"]),
                name=str(candidate.get("name") or f"Waypoint {waypoint_index:02d}"),
                type="known_parking",
                coverage_pct=round(coverage_pct, 1),
                visible_satellites=n_visible,
                total_satellites=n_total,
                zone=candidate["zone"],
                distance_from_origin_m=float(candidate["distance_along_m"]),
                eta_seconds=eta_seconds,
                max_obstruction_deg=candidate.get("max_obstruction_deg"),
                amenities=WaypointAmenities(
                    parking=bool(candidate.get("parking")),
                    restroom=bool(candidate.get("restroom")),
                    fuel=bool(candidate.get("fuel")),
                    food=False,
                ),
                best_window=candidate.get("best_window"),
            )
        )

    for idx in range(len(waypoints) - 1):
        waypoints[idx].distance_to_next_m = (
            waypoints[idx + 1].distance_from_origin_m
            - waypoints[idx].distance_from_origin_m
        )

    return waypoints


def _filter_amenity_candidates_to_corridor(
    amenities: list[dict],
    route_geometry: list[tuple[float, float]],
    corridor_m: float = 120.0,
    max_candidates: int = 20,
) -> list[dict]:
    candidates: list[dict] = []
    for amenity in amenities:
        lat = amenity.get("lat")
        lon = amenity.get("lon")
        if lat is None or lon is None:
            continue

        projected = _project_to_route(float(lat), float(lon), route_geometry)
        if projected is None:
            continue
        distance_from_route_m, distance_along_m = projected
        if distance_from_route_m > corridor_m:
            continue

        candidates.append(
            {
                **amenity,
                "lat": float(lat),
                "lon": float(lon),
                "distance_from_route_m": float(distance_from_route_m),
                "distance_along_m": float(distance_along_m),
            }
        )

    candidates.sort(
        key=lambda item: (
            float(item["distance_along_m"]),
            float(item["distance_from_route_m"]),
        )
    )

    deduped: list[dict] = []
    for candidate in candidates:
        if (
            deduped
            and abs(candidate["distance_along_m"] - deduped[-1]["distance_along_m"])
            < 150.0
        ):
            current = deduped[-1]
            current_score = (
                int(bool(current.get("parking"))),
                int(bool(current.get("fuel"))),
                -float(current.get("distance_from_route_m", 0.0)),
            )
            candidate_score = (
                int(bool(candidate.get("parking"))),
                int(bool(candidate.get("fuel"))),
                -float(candidate.get("distance_from_route_m", 0.0)),
            )
            if candidate_score > current_score:
                deduped[-1] = candidate
            continue
        deduped.append(candidate)

    return deduped[:max_candidates]


async def _analyze_los_point(
    *,
    lat: float,
    lon: float,
    timestamp: datetime,
    satellite_engine: Any,
    data_pipeline: Any,
    obstruction_engine: Any,
    start_time: float,
    radius_m: float = 220.0,
    preloaded_buildings: list[dict] | None = None,
    preloaded_building_source: str = "unknown",
    preloaded_terrain: list[dict] | None = None,
) -> dict[str, Any]:
    if _remaining_budget_seconds(start_time) <= 0.0:
        raise asyncio.TimeoutError("Route budget exhausted")

    buildings = preloaded_buildings
    building_source = preloaded_building_source
    terrain = preloaded_terrain

    if buildings is None:
        buildings_result = await data_pipeline.fetch_buildings(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
        )
        if isinstance(buildings_result, tuple):
            buildings, building_source = buildings_result
        else:
            buildings = buildings_result or []
            building_source = "unknown"
    if not isinstance(buildings, list):
        buildings = []

    if terrain is None:
        terrain = await data_pipeline.fetch_terrain(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
        )
    if not isinstance(terrain, list):
        terrain = []

    sat_timeout = min(
        settings.satellite_timeout_seconds,
        max(1.0, _remaining_budget_seconds(start_time)),
    )
    satellites = await asyncio.wait_for(
        satellite_engine.get_visible_satellites(
            lat=lat,
            lon=lon,
            elevation=0.0,
            timestamp=timestamp,
        ),
        timeout=sat_timeout,
    )

    result = obstruction_engine.analyze_position(
        lat=lat,
        lon=lon,
        elevation=0.0,
        buildings=buildings,
        terrain=terrain,
        satellites=satellites,
    )
    n_visible = int(result.get("n_clear", 0))
    n_total = int(result.get("n_total", 0))
    clear_ratio = n_visible / n_total if n_total > 0 else 0.0
    zone = _classify_zone(clear_ratio)

    max_obstruction_deg = None
    obstruction_profile = result.get("obstruction_profile") or []
    if obstruction_profile:
        max_obstruction_deg = max(
            float(point.get("elevation", 0.0))
            for point in obstruction_profile
            if isinstance(point, dict)
        )

    return {
        "lat": lat,
        "lon": lon,
        "n_visible": n_visible,
        "n_total": n_total,
        "clear_ratio": clear_ratio,
        "zone": zone,
        "max_obstruction_deg": max_obstruction_deg,
        "buildings": buildings,
        "terrain": terrain,
        "building_source": building_source,
        "has_buildings": bool(buildings),
        "has_terrain": bool(terrain),
    }


async def _compute_waypoint_reliability_window(
    *,
    lat: float,
    lon: float,
    timestamp: datetime,
    buildings: list[dict],
    building_source: str,
    terrain: list[dict],
    satellite_engine: Any,
    data_pipeline: Any,
    obstruction_engine: Any,
    start_time: float,
) -> tuple[float, str | None]:
    offsets_minutes = [0, 10, 20, 30]
    clear_ratios: list[float] = []
    best_ratio = -1.0
    best_ts = timestamp

    for offset in offsets_minutes:
        if _remaining_budget_seconds(start_time) <= 1.0:
            break
        sample_ts = timestamp + timedelta(minutes=offset)
        sample = await _analyze_los_point(
            lat=lat,
            lon=lon,
            timestamp=sample_ts,
            satellite_engine=satellite_engine,
            data_pipeline=data_pipeline,
            obstruction_engine=obstruction_engine,
            start_time=start_time,
            radius_m=220.0,
            preloaded_buildings=buildings,
            preloaded_building_source=building_source,
            preloaded_terrain=terrain,
        )
        ratio = float(sample["clear_ratio"])
        clear_ratios.append(ratio)
        if ratio > best_ratio:
            best_ratio = ratio
            best_ts = sample_ts

    if not clear_ratios:
        return 0.0, None

    reliability_pct = sum(clear_ratios) / len(clear_ratios) * 100.0
    window_span = (len(clear_ratios) - 1) * 10
    best_window = (
        f"{reliability_pct:.0f}% clear over {window_span}m; "
        f"best {best_ts.strftime('%H:%MZ')}"
    )
    return reliability_pct, best_window


def _find_dead_zones(analysis_results: list[dict]) -> list[DeadZone]:
    """Identify contiguous stretches of poor or blocked connectivity."""
    dead_zones: list[DeadZone] = []
    in_dead = False
    start: dict | None = None

    for ar in analysis_results:
        is_dead = ar["zone"] in (Zone.POOR, Zone.BLOCKED)
        if is_dead and not in_dead:
            start = ar
            in_dead = True
        elif not is_dead and in_dead and start is not None:
            dead_zones.append(
                DeadZone(
                    start_distance_m=start["distance_along_m"],
                    end_distance_m=ar["distance_along_m"],
                    length_m=ar["distance_along_m"] - start["distance_along_m"],
                    start_lat=start["lat"],
                    start_lon=start["lon"],
                    end_lat=ar["lat"],
                    end_lon=ar["lon"],
                )
            )
            in_dead = False
            start = None

    if in_dead and start is not None and analysis_results:
        end = analysis_results[-1]
        dead_zones.append(
            DeadZone(
                start_distance_m=start["distance_along_m"],
                end_distance_m=end["distance_along_m"],
                length_m=end["distance_along_m"] - start["distance_along_m"],
                start_lat=start["lat"],
                start_lon=start["lon"],
                end_lat=end["lat"],
                end_lon=end["lon"],
            )
        )

    return dead_zones


def _compute_max_gap(waypoints: list[Waypoint], total_distance_m: float) -> float:
    """Compute the longest gap between waypoint coverage points."""
    if not waypoints:
        return total_distance_m

    gaps = [waypoints[0].distance_from_origin_m]
    for i in range(len(waypoints) - 1):
        gaps.append(
            waypoints[i + 1].distance_from_origin_m
            - waypoints[i].distance_from_origin_m
        )
    gaps.append(total_distance_m - waypoints[-1].distance_from_origin_m)
    return max(gaps) if gaps else total_distance_m


def _remaining_budget_seconds(start_time: float) -> float:
    """Remaining route budget in seconds."""
    elapsed = time.time() - start_time
    return max(0.0, settings.route_timeout_seconds - elapsed)


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    message = str(exc).lower()
    if "satellite" in message:
        return "satellite_service"
    if "terrain" in message or "building" in message:
        return "data_pipeline"
    if "obstruction" in message:
        return "obstruction_engine"
    if "overpass" in message or "amenit" in message:
        return "amenities"
    return "unknown"


@router.post("/route/plan", response_model=RoutePlanResponse)
async def plan_route(
    body: RoutePlanRequest,
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
    osrm_client: Any = Depends(get_osrm_client),
    amenity_service: Any = Depends(get_amenity_service),
    request_id: str = Depends(get_request_id),
) -> RoutePlanResponse:
    """Plan route connectivity with sampled LOS analysis, amenities, and dead zones."""
    start_time = time.time()
    if body.sample_interval_m <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="sample_interval_m must be positive",
        )

    origin = await _resolve_location_async(body.origin, amenity_service)
    destination = await _resolve_location_async(body.destination, amenity_service)
    timestamp = _parse_timestamp(body.time_utc)

    route_fetch_timeout = max(5.0, min(20.0, _remaining_budget_seconds(start_time)))
    try:
        route = await asyncio.wait_for(
            asyncio.to_thread(
                osrm_client.get_route,
                origin,
                destination,
                "driving",
                [],
            ),
            timeout=route_fetch_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Route provider timed out",
        ) from exc
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not compute route. OSRM service unavailable.",
        )

    sample_points = osrm_client.sample_route_points(
        route["geometry"], interval_m=body.sample_interval_m
    )
    if not sample_points:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Route sampling failed or returned no points.",
        )

    analysis_results: list[dict] = []
    warnings: list[str] = []
    building_sources: set[str] = set()
    building_data_points = 0
    terrain_data_points = 0
    analysis_errors = 0

    for point in sample_points:
        if _remaining_budget_seconds(start_time) <= 0:
            warnings.append(
                "Route analysis budget exhausted; remaining samples skipped"
            )
            break

        try:
            sample = await _analyze_los_point(
                lat=point["lat"],
                lon=point["lon"],
                timestamp=timestamp,
                satellite_engine=satellite_engine,
                data_pipeline=data_pipeline,
                obstruction_engine=obstruction_engine,
                start_time=start_time,
                radius_m=220.0,
            )

            if sample["has_buildings"]:
                building_data_points += 1
            building_source = sample.get("building_source")
            if building_source not in ("", "none", "unknown", None):
                building_sources.add(str(building_source))
            if sample["has_terrain"]:
                terrain_data_points += 1

            analysis_results.append(
                {
                    **point,
                    "n_visible": sample["n_visible"],
                    "n_total": sample["n_total"],
                    "zone": sample["zone"],
                    "max_obstruction_deg": sample["max_obstruction_deg"],
                }
            )
        except Exception as e:
            analysis_errors += 1
            category = _classify_error(e)
            warnings.append(
                f"[{category}] Analysis failed at ({point['lat']:.4f}, {point['lon']:.4f}): {str(e)}"
            )
            analysis_results.append(
                {
                    **point,
                    "n_visible": 0,
                    "n_total": 0,
                    "zone": Zone.BLOCKED,
                    "max_obstruction_deg": None,
                }
            )

    try:
        amenities = await asyncio.wait_for(
            asyncio.to_thread(
                amenity_service.query_amenities_along_route,
                route["geometry"],
            ),
            timeout=min(12.0, max(1.0, _remaining_budget_seconds(start_time))),
        )
    except Exception as exc:
        logger.warning("[%s] Amenity lookup degraded: %s", request_id, exc)
        warnings.append("Amenities unavailable due to upstream timeout")
        amenities = []

    candidate_inputs = _filter_amenity_candidates_to_corridor(
        amenities=amenities,
        route_geometry=route["geometry"],
        corridor_m=settings.route_candidate_corridor_meters,
        max_candidates=20,
    )
    if amenities and not candidate_inputs:
        warnings.append(
            "No parking/fuel/rest candidates fell inside the drivable route corridor"
        )

    candidate_results: list[dict] = []
    for candidate in candidate_inputs:
        if _remaining_budget_seconds(start_time) <= 0:
            warnings.append(
                "Waypoint candidate analysis stopped due to route timeout budget"
            )
            break

        try:
            candidate_analysis = await _analyze_los_point(
                lat=float(candidate["lat"]),
                lon=float(candidate["lon"]),
                timestamp=timestamp,
                satellite_engine=satellite_engine,
                data_pipeline=data_pipeline,
                obstruction_engine=obstruction_engine,
                start_time=start_time,
                radius_m=250.0,
            )

            reliability_pct, best_window = await _compute_waypoint_reliability_window(
                lat=float(candidate["lat"]),
                lon=float(candidate["lon"]),
                timestamp=timestamp,
                buildings=candidate_analysis["buildings"],
                building_source=str(
                    candidate_analysis.get("building_source") or "unknown"
                ),
                terrain=candidate_analysis["terrain"],
                satellite_engine=satellite_engine,
                data_pipeline=data_pipeline,
                obstruction_engine=obstruction_engine,
                start_time=start_time,
            )

            if candidate_analysis["has_buildings"]:
                building_data_points += 1
            candidate_building_source = candidate_analysis.get("building_source")
            if candidate_building_source not in ("", "none", "unknown", None):
                building_sources.add(str(candidate_building_source))
            if candidate_analysis["has_terrain"]:
                terrain_data_points += 1

            candidate_results.append(
                {
                    "lat": float(candidate["lat"]),
                    "lon": float(candidate["lon"]),
                    "name": candidate.get("name") or candidate.get("type") or "Stop",
                    "parking": bool(candidate.get("parking")),
                    "restroom": bool(candidate.get("restroom")),
                    "fuel": bool(candidate.get("fuel")),
                    "distance_from_route_m": float(
                        candidate.get("distance_from_route_m", 0.0)
                    ),
                    "distance_along_m": float(candidate.get("distance_along_m", 0.0)),
                    "n_visible": int(candidate_analysis["n_visible"]),
                    "n_total": int(candidate_analysis["n_total"]),
                    "zone": candidate_analysis["zone"],
                    "max_obstruction_deg": candidate_analysis["max_obstruction_deg"],
                    "reliability_pct": round(reliability_pct, 1),
                    "best_window": best_window,
                }
            )
        except Exception as exc:
            warnings.append(
                "[amenity_analysis] Skipped candidate at "
                f"({candidate['lat']:.4f}, {candidate['lon']:.4f}): {exc}"
            )

    waypoints = _rank_waypoints(candidate_results, route)
    if not waypoints:
        warnings.append(
            "No parking/fuel/rest locations met connectivity criteria on this route"
        )
    dead_zones = _find_dead_zones(analysis_results)

    signal_forecast = [_signal_label(ar["zone"]) for ar in analysis_results]

    route_features = []
    for i in range(len(analysis_results) - 1):
        a = analysis_results[i]
        b = analysis_results[i + 1]
        route_features.append(
            GeoJSONFeature(
                geometry=GeoJSONGeometry(
                    type="LineString",
                    coordinates=[[a["lon"], a["lat"]], [b["lon"], b["lat"]]],
                ),
                properties={
                    "signal": _signal_label(a["zone"]),
                    "zone": a["zone"].value,
                    "visible_satellites": a["n_visible"],
                    "total_satellites": a["n_total"],
                },
            )
        )
    route_geojson = GeoJSONFeatureCollection(features=route_features)

    total_dead_m = sum(dz.length_m for dz in dead_zones)
    max_gap_m = _compute_max_gap(waypoints, route["distance_m"])
    covered_m = max(0.0, route["distance_m"] - total_dead_m)
    coverage_pct = (
        covered_m / route["distance_m"] * 100.0 if route["distance_m"] > 0 else 0.0
    )

    mission_summary = MissionSummary(
        origin_name=body.origin.address,
        destination_name=body.destination.address,
        total_distance_m=route["distance_m"],
        total_duration_s=route["duration_s"],
        num_waypoints=len(waypoints),
        max_gap_m=max_gap_m,
        num_dead_zones=len(dead_zones),
        dead_zone_total_m=total_dead_m,
        route_coverage_pct=round(coverage_pct, 1),
    )

    total_los_checks = len(analysis_results) + len(candidate_results)

    if building_data_points == 0:
        building_quality = "none"
        warnings.append(
            "No building data available along route - obstruction analysis may be inaccurate"
        )
    elif total_los_checks > 0 and building_data_points == total_los_checks:
        building_quality = "full"
    else:
        building_quality = "partial"

    terrain_quality = (
        "full"
        if total_los_checks > 0 and terrain_data_points == total_los_checks
        else "none"
    )
    if terrain_quality == "none":
        warnings.append("Terrain elevation data unavailable for route samples")

    if analysis_errors > 0:
        warnings.append(
            f"{analysis_errors} sample point(s) failed and were marked as blocked"
        )

    sources = ["osrm:driving", "satellites"]
    if building_sources:
        sources.extend([f"buildings:{src}" for src in sorted(building_sources)])
    elif building_data_points > 0:
        sources.append("buildings")
    if terrain_data_points > 0:
        sources.append("terrain:copernicus_glo30")
    if amenities:
        sources.append("amenities:overpass:parking-fuel-rest")
    if body.origin.address or body.destination.address:
        sources.append("geocoding:nominatim")

    data_quality = DataQuality(
        buildings=building_quality,
        terrain=terrain_quality,
        satellites="live",
        sources=sources,
        warnings=warnings,
    )

    elapsed_s = time.time() - start_time
    logger.info(
        "[%s] Route planning completed in %.2fs: samples=%d, waypoints=%d, dead_zones=%d",
        request_id,
        elapsed_s,
        len(analysis_results),
        len(waypoints),
        len(dead_zones),
    )

    return RoutePlanResponse(
        route_geojson=route_geojson,
        waypoints=waypoints,
        dead_zones=dead_zones,
        mission_summary=mission_summary,
        data_quality=data_quality,
        signal_forecast=signal_forecast,
    )
