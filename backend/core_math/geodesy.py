"""Canonical WGS84 and local-frame geometry helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .constants import (
    DEG_TO_RAD,
    EARTH_MEAN_RADIUS_M,
    RAD_TO_DEG,
    WGS84_A_M,
    WGS84_B_M,
    WGS84_E2,
    WGS84_F,
)
from .types import GeodesicResult


def validate_lat_lon(lat_deg: float, lon_deg: float) -> None:
    """Validate geodetic input ranges."""
    if not (-90.0 <= float(lat_deg) <= 90.0):
        raise ValueError(f"Latitude out of range: {lat_deg}")
    if not (-180.0 <= float(lon_deg) <= 180.0):
        raise ValueError(f"Longitude out of range: {lon_deg}")


def normalize_longitude(lon_deg: float) -> float:
    """Normalize longitude into [-180, 180)."""
    normalized = ((float(lon_deg) + 180.0) % 360.0) - 180.0
    return 180.0 if normalized == -180.0 else normalized


def geodetic_to_ecef(lat_deg: float, lon_deg: float, altitude_m: float) -> tuple[float, float, float]:
    """Convert WGS84 geodetic coordinates to ECEF meters."""
    validate_lat_lon(lat_deg, lon_deg)
    lat_rad = float(lat_deg) * DEG_TO_RAD
    lon_rad = float(lon_deg) * DEG_TO_RAD

    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)

    radius = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)

    x = (radius + altitude_m) * cos_lat * cos_lon
    y = (radius + altitude_m) * cos_lat * sin_lon
    z = (radius * (1.0 - WGS84_E2) + altitude_m) * sin_lat
    return x, y, z


def ecef_to_geodetic(x_m: float, y_m: float, z_m: float) -> tuple[float, float, float]:
    """Convert ECEF meters to WGS84 geodetic coordinates."""
    lon = math.atan2(y_m, x_m)
    p = math.hypot(x_m, y_m)

    if p == 0.0:
        lat = math.copysign(math.pi / 2.0, z_m)
        altitude = abs(z_m) - WGS84_B_M
        return lat * RAD_TO_DEG, normalize_longitude(lon * RAD_TO_DEG), altitude

    lat = math.atan2(z_m, p * (1.0 - WGS84_E2))
    for _ in range(8):
        sin_lat = math.sin(lat)
        radius = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        altitude = p / math.cos(lat) - radius
        next_lat = math.atan2(z_m, p * (1.0 - WGS84_E2 * radius / (radius + altitude)))
        if abs(next_lat - lat) < 1e-14:
            lat = next_lat
            break
        lat = next_lat

    sin_lat = math.sin(lat)
    radius = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    altitude = p / math.cos(lat) - radius
    return lat * RAD_TO_DEG, normalize_longitude(lon * RAD_TO_DEG), altitude


def ecef_delta_to_enu(
    dx_m: float,
    dy_m: float,
    dz_m: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
) -> tuple[float, float, float]:
    """Rotate an ECEF delta vector into local ENU coordinates."""
    validate_lat_lon(ref_lat_deg, ref_lon_deg)
    ref_lat_rad = ref_lat_deg * DEG_TO_RAD
    ref_lon_rad = ref_lon_deg * DEG_TO_RAD

    sin_lat = math.sin(ref_lat_rad)
    cos_lat = math.cos(ref_lat_rad)
    sin_lon = math.sin(ref_lon_rad)
    cos_lon = math.cos(ref_lon_rad)

    east = -sin_lon * dx_m + cos_lon * dy_m
    north = -sin_lat * cos_lon * dx_m - sin_lat * sin_lon * dy_m + cos_lat * dz_m
    up = cos_lat * cos_lon * dx_m + cos_lat * sin_lon * dy_m + sin_lat * dz_m
    return east, north, up


def enu_to_ecef_delta(
    east_m: float,
    north_m: float,
    up_m: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
) -> tuple[float, float, float]:
    """Rotate an ENU delta vector into ECEF coordinates."""
    validate_lat_lon(ref_lat_deg, ref_lon_deg)
    ref_lat_rad = ref_lat_deg * DEG_TO_RAD
    ref_lon_rad = ref_lon_deg * DEG_TO_RAD

    sin_lat = math.sin(ref_lat_rad)
    cos_lat = math.cos(ref_lat_rad)
    sin_lon = math.sin(ref_lon_rad)
    cos_lon = math.cos(ref_lon_rad)

    dx = -sin_lon * east_m - sin_lat * cos_lon * north_m + cos_lat * cos_lon * up_m
    dy = cos_lon * east_m - sin_lat * sin_lon * north_m + cos_lat * sin_lon * up_m
    dz = cos_lat * north_m + sin_lat * up_m
    return dx, dy, dz


def geodetic_to_enu(
    lat_deg: float,
    lon_deg: float,
    altitude_m: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
    ref_altitude_m: float,
) -> tuple[float, float, float]:
    """Convert a target WGS84 point to ENU relative to a reference point."""
    tx, ty, tz = geodetic_to_ecef(lat_deg, lon_deg, altitude_m)
    rx, ry, rz = geodetic_to_ecef(ref_lat_deg, ref_lon_deg, ref_altitude_m)
    return ecef_delta_to_enu(tx - rx, ty - ry, tz - rz, ref_lat_deg, ref_lon_deg)


def enu_to_geodetic(
    east_m: float,
    north_m: float,
    up_m: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
    ref_altitude_m: float,
) -> tuple[float, float, float]:
    """Convert an ENU vector back to a WGS84 point."""
    rx, ry, rz = geodetic_to_ecef(ref_lat_deg, ref_lon_deg, ref_altitude_m)
    dx, dy, dz = enu_to_ecef_delta(east_m, north_m, up_m, ref_lat_deg, ref_lon_deg)
    return ecef_to_geodetic(rx + dx, ry + dy, rz + dz)


def azimuth_from_enu(east_m: float, north_m: float) -> float:
    """Compute azimuth clockwise from true north."""
    if east_m == 0.0 and north_m == 0.0:
        return 0.0
    return math.degrees(math.atan2(east_m, north_m)) % 360.0


def elevation_from_enu(east_m: float, north_m: float, up_m: float) -> float:
    """Compute elevation angle above the horizon."""
    horizontal = math.hypot(east_m, north_m)
    if horizontal == 0.0:
        if up_m > 0.0:
            return 90.0
        if up_m < 0.0:
            return -90.0
        return 0.0
    return math.degrees(math.atan2(up_m, horizontal))


def slant_range_m_from_enu(east_m: float, north_m: float, up_m: float) -> float:
    """Compute observer-to-target slant range in meters."""
    return math.sqrt(east_m * east_m + north_m * north_m + up_m * up_m)


def haversine_distance_m(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Fast spherical distance helper for coarse screening."""
    validate_lat_lon(lat1_deg, lon1_deg)
    validate_lat_lon(lat2_deg, lon2_deg)

    lat1 = lat1_deg * DEG_TO_RAD
    lat2 = lat2_deg * DEG_TO_RAD
    d_lat = (lat2_deg - lat1_deg) * DEG_TO_RAD
    d_lon = (lon2_deg - lon1_deg) * DEG_TO_RAD

    sin_d_lat = math.sin(d_lat / 2.0)
    sin_d_lon = math.sin(d_lon / 2.0)
    a = sin_d_lat * sin_d_lat + math.cos(lat1) * math.cos(lat2) * sin_d_lon * sin_d_lon
    a = min(1.0, max(0.0, a))
    return 2.0 * EARTH_MEAN_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _spherical_initial_bearing(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    lat1 = lat1_deg * DEG_TO_RAD
    lat2 = lat2_deg * DEG_TO_RAD
    lon_delta = (lon2_deg - lon1_deg) * DEG_TO_RAD
    x = math.sin(lon_delta) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(lon_delta)
    )
    return math.degrees(math.atan2(x, y)) % 360.0


def vincenty_inverse(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
    max_iterations: int = 200,
    tolerance: float = 1e-12,
) -> GeodesicResult:
    """Compute ellipsoidal inverse geodesic on WGS84 using Vincenty's method."""
    validate_lat_lon(lat1_deg, lon1_deg)
    validate_lat_lon(lat2_deg, lon2_deg)

    if lat1_deg == lat2_deg and lon1_deg == lon2_deg:
        return GeodesicResult(0.0, 0.0, 0.0)

    reduced_lat1 = math.atan((1.0 - WGS84_F) * math.tan(lat1_deg * DEG_TO_RAD))
    reduced_lat2 = math.atan((1.0 - WGS84_F) * math.tan(lat2_deg * DEG_TO_RAD))
    sin_u1 = math.sin(reduced_lat1)
    cos_u1 = math.cos(reduced_lat1)
    sin_u2 = math.sin(reduced_lat2)
    cos_u2 = math.cos(reduced_lat2)

    lon_diff = (lon2_deg - lon1_deg) * DEG_TO_RAD
    lam = lon_diff

    for _ in range(max_iterations):
        sin_lam = math.sin(lam)
        cos_lam = math.cos(lam)
        sin_sigma = math.sqrt(
            (cos_u2 * sin_lam) ** 2
            + (cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam) ** 2
        )
        if sin_sigma == 0.0:
            return GeodesicResult(0.0, 0.0, 0.0)
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1.0 - sin_alpha * sin_alpha
        cos2_sigma_m = 0.0 if cos_sq_alpha == 0.0 else cos_sigma - 2.0 * sin_u1 * sin_u2 / cos_sq_alpha
        c = WGS84_F / 16.0 * cos_sq_alpha * (4.0 + WGS84_F * (4.0 - 3.0 * cos_sq_alpha))
        next_lam = lon_diff + (1.0 - c) * WGS84_F * sin_alpha * (
            sigma
            + c
            * sin_sigma
            * (
                cos2_sigma_m
                + c * cos_sigma * (-1.0 + 2.0 * cos2_sigma_m * cos2_sigma_m)
            )
        )
        if abs(next_lam - lam) <= tolerance:
            lam = next_lam
            break
        lam = next_lam
    else:
        distance = haversine_distance_m(lat1_deg, lon1_deg, lat2_deg, lon2_deg)
        bearing = _spherical_initial_bearing(lat1_deg, lon1_deg, lat2_deg, lon2_deg)
        return GeodesicResult(distance, bearing, bearing)

    u_sq = (1.0 - sin_alpha * sin_alpha) * ((WGS84_A_M * WGS84_A_M - WGS84_B_M * WGS84_B_M) / (WGS84_B_M * WGS84_B_M))
    a_coeff = 1.0 + u_sq / 16384.0 * (4096.0 + u_sq * (-768.0 + u_sq * (320.0 - 175.0 * u_sq)))
    b_coeff = u_sq / 1024.0 * (256.0 + u_sq * (-128.0 + u_sq * (74.0 - 47.0 * u_sq)))
    delta_sigma = b_coeff * sin_sigma * (
        cos2_sigma_m
        + 0.25
        * b_coeff
        * (
            cos_sigma * (-1.0 + 2.0 * cos2_sigma_m * cos2_sigma_m)
            - b_coeff
            / 6.0
            * cos2_sigma_m
            * (-3.0 + 4.0 * sin_sigma * sin_sigma)
            * (-3.0 + 4.0 * cos2_sigma_m * cos2_sigma_m)
        )
    )
    distance = WGS84_B_M * a_coeff * (sigma - delta_sigma)

    initial = math.degrees(
        math.atan2(cos_u2 * math.sin(lam), cos_u1 * sin_u2 - sin_u1 * cos_u2 * math.cos(lam))
    ) % 360.0
    final = math.degrees(
        math.atan2(cos_u1 * math.sin(lam), -sin_u1 * cos_u2 + cos_u1 * sin_u2 * math.cos(lam))
    ) % 360.0
    return GeodesicResult(distance, initial, final)


def vincenty_direct(
    lat_deg: float,
    lon_deg: float,
    initial_bearing_deg: float,
    distance_m: float,
    max_iterations: int = 200,
    tolerance: float = 1e-12,
) -> tuple[float, float, float]:
    """Project a WGS84 point by distance and initial bearing using Vincenty."""
    validate_lat_lon(lat_deg, lon_deg)
    if distance_m == 0.0:
        return lat_deg, lon_deg, initial_bearing_deg % 360.0

    alpha1 = initial_bearing_deg * DEG_TO_RAD
    tan_u1 = (1.0 - WGS84_F) * math.tan(lat_deg * DEG_TO_RAD)
    u1 = math.atan(tan_u1)
    sin_u1 = math.sin(u1)
    cos_u1 = math.cos(u1)
    sin_alpha1 = math.sin(alpha1)
    cos_alpha1 = math.cos(alpha1)

    sigma1 = math.atan2(tan_u1, cos_alpha1)
    sin_alpha = cos_u1 * sin_alpha1
    cos_sq_alpha = 1.0 - sin_alpha * sin_alpha
    u_sq = cos_sq_alpha * ((WGS84_A_M * WGS84_A_M - WGS84_B_M * WGS84_B_M) / (WGS84_B_M * WGS84_B_M))
    a_coeff = 1.0 + u_sq / 16384.0 * (4096.0 + u_sq * (-768.0 + u_sq * (320.0 - 175.0 * u_sq)))
    b_coeff = u_sq / 1024.0 * (256.0 + u_sq * (-128.0 + u_sq * (74.0 - 47.0 * u_sq)))

    sigma = distance_m / (WGS84_B_M * a_coeff)
    for _ in range(max_iterations):
        two_sigma_m = 2.0 * sigma1 + sigma
        sin_sigma = math.sin(sigma)
        cos_sigma = math.cos(sigma)
        cos_two_sigma_m = math.cos(two_sigma_m)
        delta_sigma = b_coeff * sin_sigma * (
            cos_two_sigma_m
            + 0.25
            * b_coeff
            * (
                cos_sigma * (-1.0 + 2.0 * cos_two_sigma_m * cos_two_sigma_m)
                - b_coeff
                / 6.0
                * cos_two_sigma_m
                * (-3.0 + 4.0 * sin_sigma * sin_sigma)
                * (-3.0 + 4.0 * cos_two_sigma_m * cos_two_sigma_m)
            )
        )
        next_sigma = distance_m / (WGS84_B_M * a_coeff) + delta_sigma
        if abs(next_sigma - sigma) <= tolerance:
            sigma = next_sigma
            break
        sigma = next_sigma

    sin_sigma = math.sin(sigma)
    cos_sigma = math.cos(sigma)
    two_sigma_m = 2.0 * sigma1 + sigma
    cos_two_sigma_m = math.cos(two_sigma_m)

    numerator = sin_u1 * cos_sigma + cos_u1 * sin_sigma * cos_alpha1
    denominator = (1.0 - WGS84_F) * math.sqrt(
        sin_alpha * sin_alpha
        + (sin_u1 * sin_sigma - cos_u1 * cos_sigma * cos_alpha1) ** 2
    )
    lat2 = math.atan2(numerator, denominator)
    lam = math.atan2(
        sin_sigma * sin_alpha1,
        cos_u1 * cos_sigma - sin_u1 * sin_sigma * cos_alpha1,
    )
    c = WGS84_F / 16.0 * cos_sq_alpha * (4.0 + WGS84_F * (4.0 - 3.0 * cos_sq_alpha))
    lon_delta = lam - (1.0 - c) * WGS84_F * sin_alpha * (
        sigma
        + c
        * sin_sigma
        * (
            cos_two_sigma_m
            + c * cos_sigma * (-1.0 + 2.0 * cos_two_sigma_m * cos_two_sigma_m)
        )
    )
    lon2 = normalize_longitude(lon_deg + lon_delta * RAD_TO_DEG)
    final_bearing = math.degrees(
        math.atan2(
            sin_alpha,
            -sin_u1 * sin_sigma + cos_u1 * cos_sigma * cos_alpha1,
        )
    ) % 360.0
    return lat2 * RAD_TO_DEG, lon2, final_bearing
