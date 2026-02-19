"""OSRM client for route planning."""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OSRM_BASE_URL = "https://router.project-osrm.org"


class OSRMClient:
    """Client for Open Source Routing Machine (OSRM) API."""

    def __init__(
        self,
        base_url: str = OSRM_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.4,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.retry_backoff_s = max(0.05, float(retry_backoff_s))

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        profile: str = "driving",
        fallback_profiles: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Fetch route geometry and metadata from OSRM.

        Args:
            origin: (lat, lon) origin tuple.
            destination: (lat, lon) destination tuple.
            profile: OSRM profile: driving, cycling, or walking.

        Returns:
            dict with keys geometry, distance_m, duration_s, or None on failure.
        """
        profiles = [profile]
        defaults = fallback_profiles or ["driving", "walking", "cycling"]
        for alt in defaults:
            if alt not in profiles:
                profiles.append(alt)

        coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        }
        last_error: Optional[str] = None

        for current_profile in profiles:
            url = f"{self.base_url}/route/v1/{current_profile}/{coords}"
            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = requests.get(url, params=params, timeout=self.timeout)
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise requests.RequestException(
                            f"transient OSRM status {resp.status_code}"
                        )
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("code") != "Ok" or not data.get("routes"):
                        last_error = str(data.get("code", "no_route"))
                        logger.warning(
                            "OSRM returned no route for profile %s: %s",
                            current_profile,
                            last_error,
                        )
                        break

                    route = data["routes"][0]
                    geometry = [
                        (coord[1], coord[0]) for coord in route["geometry"]["coordinates"]
                    ]
                    return {
                        "geometry": geometry,
                        "distance_m": float(route["distance"]),
                        "duration_s": float(route["duration"]),
                        "profile": current_profile,
                    }
                except requests.RequestException as e:
                    last_error = str(e)
                    if attempt < self.max_retries:
                        backoff = self.retry_backoff_s * (2 ** (attempt - 1))
                        time.sleep(backoff)
                    else:
                        logger.warning(
                            "OSRM request failed for profile %s after %d attempts: %s",
                            current_profile,
                            self.max_retries,
                            e,
                        )

        logger.error("OSRM request exhausted all profiles (%s): %s", ",".join(profiles), last_error)
        return None

    def sample_route_points(
        self,
        geometry: list[tuple[float, float]],
        interval_m: float = 500.0,
    ) -> list[dict]:
        """Sample points along route geometry at fixed intervals.

        Args:
            geometry: List of (lat, lon) vertices.
            interval_m: Sampling interval in meters.

        Returns:
            List of dicts with lat, lon, distance_along_m.
        """
        if not geometry or len(geometry) < 2:
            return []

        points = [{
            "lat": geometry[0][0],
            "lon": geometry[0][1],
            "distance_along_m": 0.0,
        }]
        accumulated = 0.0
        next_sample = float(interval_m)

        for i in range(1, len(geometry)):
            seg_start = geometry[i - 1]
            seg_end = geometry[i]
            seg_dist = self._haversine(seg_start[0], seg_start[1], seg_end[0], seg_end[1])
            accumulated += seg_dist

            while seg_dist > 0 and accumulated >= next_sample:
                overshoot = accumulated - next_sample
                ratio = 1.0 - (overshoot / seg_dist)
                lat = seg_start[0] + ratio * (seg_end[0] - seg_start[0])
                lon = seg_start[1] + ratio * (seg_end[1] - seg_start[1])
                points.append({
                    "lat": lat,
                    "lon": lon,
                    "distance_along_m": next_sample,
                })
                next_sample += interval_m

        total_distance = accumulated
        end_lat, end_lon = geometry[-1]
        if (
            not points
            or points[-1]["lat"] != end_lat
            or points[-1]["lon"] != end_lon
        ):
            points.append({
                "lat": end_lat,
                "lon": end_lon,
                "distance_along_m": total_distance,
            })

        return points

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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
