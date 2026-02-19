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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from config import settings
from dependencies import (
    get_amenity_service,
    get_data_pipeline,
    get_obstruction_engine,
    get_osrm_client,
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


def _resolve_location(location: RouteLocation, amenity_service: Any) -> tuple[float, float]:
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


def _rank_waypoints(
    analysis_results: list[dict],
    amenities: list[dict],
    route: dict,
) -> list[Waypoint]:
    """Score and rank potential stopping points."""
    waypoints: list[Waypoint] = []
    wp_count = 0
    avg_speed_mps = (
        route["distance_m"] / route["duration_s"] if route.get("duration_s", 0) > 0 else 20.0
    )

    # Prefer known parking/rest/fuel amenities first.
    for amenity in amenities:
        nearest = min(
            analysis_results,
            key=lambda ar: _haversine_m(
                ar["lat"], ar["lon"], amenity["lat"], amenity["lon"]
            ),
        )
        if nearest.get("n_total", 0) <= 0:
            continue

        wp_count += 1
        coverage_pct = (
            nearest["n_visible"] / nearest["n_total"] * 100.0
            if nearest["n_total"] > 0
            else 0.0
        )
        eta_seconds = nearest["distance_along_m"] / avg_speed_mps
        max_obstruction_deg = nearest.get("max_obstruction_deg")

        name = amenity.get("name") or (
            "Rest Area" if amenity.get("parking") else f"Stop {wp_count:02d}"
        )

        waypoints.append(
            Waypoint(
                id=f"WP-{wp_count:02d}",
                lat=amenity["lat"],
                lon=amenity["lon"],
                name=name,
                type="known_parking",
                coverage_pct=round(coverage_pct, 1),
                visible_satellites=nearest["n_visible"],
                total_satellites=nearest["n_total"],
                zone=nearest["zone"],
                distance_from_origin_m=nearest["distance_along_m"],
                eta_seconds=eta_seconds,
                max_obstruction_deg=max_obstruction_deg,
                amenities=WaypointAmenities(
                    parking=bool(amenity.get("parking")),
                    restroom=bool(amenity.get("restroom")),
                    fuel=bool(amenity.get("fuel")),
                    food=bool(amenity.get("food")),
                ),
            )
        )

    # Add high-signal pullovers that are not close to known amenities.
    for ar in analysis_results:
        if ar["zone"] not in (Zone.EXCELLENT, Zone.GOOD):
            continue

        too_close = any(
            _haversine_m(ar["lat"], ar["lon"], wp.lat, wp.lon) < 500.0
            for wp in waypoints
        )
        if too_close:
            continue

        wp_count += 1
        coverage_pct = (
            ar["n_visible"] / ar["n_total"] * 100.0 if ar["n_total"] > 0 else 0.0
        )
        eta_seconds = ar["distance_along_m"] / avg_speed_mps

        waypoints.append(
            Waypoint(
                id=f"WP-{wp_count:02d}",
                lat=ar["lat"],
                lon=ar["lon"],
                name=f"Pullover at {ar['distance_along_m'] / 1609.34:.1f}mi",
                type="pullover",
                coverage_pct=round(coverage_pct, 1),
                visible_satellites=ar["n_visible"],
                total_satellites=ar["n_total"],
                zone=ar["zone"],
                distance_from_origin_m=ar["distance_along_m"],
                eta_seconds=eta_seconds,
                max_obstruction_deg=ar.get("max_obstruction_deg"),
            )
        )

    waypoints.sort(key=lambda wp: wp.distance_from_origin_m)
    for i in range(len(waypoints) - 1):
        waypoints[i].distance_to_next_m = (
            waypoints[i + 1].distance_from_origin_m - waypoints[i].distance_from_origin_m
        )
    return waypoints


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
            waypoints[i + 1].distance_from_origin_m - waypoints[i].distance_from_origin_m
        )
    gaps.append(total_distance_m - waypoints[-1].distance_from_origin_m)
    return max(gaps) if gaps else total_distance_m


@router.post("/route/plan", response_model=RoutePlanResponse)
async def plan_route(
    body: RoutePlanRequest,
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
    osrm_client: Any = Depends(get_osrm_client),
    amenity_service: Any = Depends(get_amenity_service),
) -> RoutePlanResponse:
    """Plan route connectivity with sampled LOS analysis, amenities, and dead zones."""
    start_time = time.time()

    origin = _resolve_location(body.origin, amenity_service)
    destination = _resolve_location(body.destination, amenity_service)
    timestamp = _parse_timestamp(body.time_utc)

    route = await asyncio.to_thread(osrm_client.get_route, origin, destination)
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
        try:
            satellites = await satellite_engine.get_visible_satellites(
                lat=point["lat"],
                lon=point["lon"],
                elevation=0.0,
                timestamp=timestamp,
            )

            buildings_result = await data_pipeline.fetch_buildings(
                lat=point["lat"],
                lon=point["lon"],
                radius_m=200.0,
            )
            if isinstance(buildings_result, tuple):
                buildings, building_source = buildings_result
            else:
                buildings = buildings_result or []
                building_source = "unknown"

            terrain = await data_pipeline.fetch_terrain(
                lat=point["lat"],
                lon=point["lon"],
                radius_m=200.0,
            )

            if buildings:
                building_data_points += 1
            if building_source not in ("", "none", "unknown", None):
                building_sources.add(str(building_source))
            if terrain:
                terrain_data_points += 1

            result = obstruction_engine.analyze_position(
                lat=point["lat"],
                lon=point["lon"],
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
                    float(p.get("elevation", 0.0))
                    for p in obstruction_profile
                    if isinstance(p, dict)
                )

            analysis_results.append({
                **point,
                "n_visible": n_visible,
                "n_total": n_total,
                "zone": zone,
                "max_obstruction_deg": max_obstruction_deg,
            })
        except Exception as e:
            analysis_errors += 1
            warnings.append(
                f"Analysis failed at ({point['lat']:.4f}, {point['lon']:.4f}): {str(e)}"
            )
            analysis_results.append({
                **point,
                "n_visible": 0,
                "n_total": 0,
                "zone": Zone.BLOCKED,
                "max_obstruction_deg": None,
            })

    amenities = await asyncio.to_thread(
        amenity_service.query_amenities_along_route, route["geometry"]
    )
    waypoints = _rank_waypoints(analysis_results, amenities, route)
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

    if building_data_points == 0:
        building_quality = "none"
        warnings.append(
            "No building data available along route - obstruction analysis may be inaccurate"
        )
    elif building_data_points == len(analysis_results):
        building_quality = "full"
    else:
        building_quality = "partial"

    terrain_quality = "full" if terrain_data_points > 0 else "none"
    if terrain_quality == "none":
        warnings.append("Terrain elevation data unavailable for route samples")

    if analysis_errors > 0:
        warnings.append(
            f"{analysis_errors} sample point(s) failed and were marked as blocked"
        )

    sources = ["osrm", "satellites"]
    if building_sources:
        sources.extend([f"buildings:{src}" for src in sorted(building_sources)])
    elif building_data_points > 0:
        sources.append("buildings")
    if terrain_data_points > 0:
        sources.append("terrain:copernicus_glo30")
    if amenities:
        sources.append("amenities:overpass")
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
        "Route planning completed in %.2fs: samples=%d, waypoints=%d, dead_zones=%d",
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
