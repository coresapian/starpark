#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkSpot ENU Coordinate Utilities

BSD 3-Clause License

Copyright (c) 2024, LinkSpot Project Contributors
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

================================================================================

ENU (East-North-Up) Coordinate System Utilities

The ENU coordinate system is a local tangent plane coordinate system where:
- E (East): Points toward geographic east along the local parallel
- N (North): Points toward geographic north along the local meridian  
- U (Up): Points toward the zenith (away from Earth's center)

This system is ideal for local geometric calculations because:
1. Azimuth angles are measured directly from North in the E-N plane
2. Elevation angles are measured from the horizontal (E-N) plane
3. Distances are locally Cartesian (meters) for small regions (<100km)

Geometric relationships in ENU:
- Azimuth = atan2(E, N)  [measured clockwise from North]
- Horizontal distance = sqrt(E² + N²)
- Elevation angle = atan2(U, horizontal_distance)
"""

import numpy as np
from typing import Union, Tuple
import math

# WGS84 ellipsoid parameters
WGS84_A = 6378137.0           # Semi-major axis (meters)
WGS84_E2 = 0.00669437999014   # First eccentricity squared

# Type aliases for clarity
FloatOrArray = Union[float, np.ndarray]


def wgs84_to_enu(
    lat: FloatOrArray,
    lon: FloatOrArray,
    elevation: FloatOrArray,
    ref_lat: float,
    ref_lon: float,
    ref_elev: float
) -> Tuple[FloatOrArray, FloatOrArray, FloatOrArray]:
    """
    Convert WGS84 (lat, lon, elevation) coordinates to ENU coordinates.
    
    This transformation converts geodetic coordinates to a local Cartesian
    system centered at (ref_lat, ref_lon, ref_elev). The ENU system is
    ideal for local geometric calculations like azimuth and elevation angles.
    
    Mathematical approach:
    1. Convert both points to ECEF (Earth-Centered, Earth-Fixed) coordinates
    2. Rotate the difference vector to align with local ENU axes at reference
    
    Args:
        lat: Latitude(s) in decimal degrees (-90 to 90)
        lon: Longitude(s) in decimal degrees (-180 to 180)
        elevation: Height(s) above WGS84 ellipsoid in meters
        ref_lat: Reference latitude for ENU origin (decimal degrees)
        ref_lon: Reference longitude for ENU origin (decimal degrees)
        ref_elev: Reference elevation for ENU origin (meters)
    
    Returns:
        Tuple of (e, n, u) coordinates in meters relative to reference point:
        - e: East coordinate (positive = east of reference)
        - n: North coordinate (positive = north of reference)
        - u: Up coordinate (positive = above reference)
    
    Example:
        >>> e, n, u = wgs84_to_enu(40.7128, -74.0060, 10.0, 
        ...                        40.7127, -74.0061, 0.0)
        >>> print(f"Position is {e:.1f}m east, {n:.1f}m north")
    """
    # Convert to radians for trigonometric calculations
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    # Convert target point(s) to ECEF coordinates
    # ECEF: X points toward (0°N, 0°E), Y toward (0°N, 90°E), Z toward North Pole
    x, y, z = _geodetic_to_ecef(lat_rad, lon_rad, elevation)
    
    # Convert reference point to ECEF
    x0, y0, z0 = _geodetic_to_ecef(ref_lat_rad, ref_lon_rad, ref_elev)
    
    # Compute difference vector in ECEF
    dx = x - x0
    dy = y - y0
    dz = z - z0
    
    # Rotate ECEF difference to ENU coordinates
    # Rotation matrix from ECEF to ENU at reference point:
    # [ -sin(lon)           cos(lon)           0         ]
    # [ -sin(lat)*cos(lon) -sin(lat)*sin(lon) cos(lat)  ]
    # [  cos(lat)*cos(lon)  cos(lat)*sin(lon) sin(lat)  ]
    
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # Apply rotation to get ENU coordinates
    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    
    return e, n, u


def enu_to_wgs84(
    e: FloatOrArray,
    n: FloatOrArray,
    u: FloatOrArray,
    ref_lat: float,
    ref_lon: float,
    ref_elev: float
) -> Tuple[FloatOrArray, FloatOrArray, FloatOrArray]:
    """
    Convert ENU coordinates back to WGS84 (lat, lon, elevation).
    
    This is the inverse of wgs84_to_enu(). It converts local Cartesian
    coordinates back to geodetic coordinates.
    
    Mathematical approach:
    1. Convert reference point to ECEF
    2. Rotate ENU vector to ECEF frame
    3. Add to reference ECEF position
    4. Convert back to geodetic
    
    Args:
        e: East coordinate(s) in meters (positive = east)
        n: North coordinate(s) in meters (positive = north)
        u: Up coordinate(s) in meters (positive = up)
        ref_lat: Reference latitude (decimal degrees)
        ref_lon: Reference longitude (decimal degrees)
        ref_elev: Reference elevation (meters)
    
    Returns:
        Tuple of (lat, lon, elevation) in WGS84:
        - lat: Latitude in decimal degrees
        - lon: Longitude in decimal degrees
        - elevation: Height above WGS84 ellipsoid in meters
    """
    # Convert reference to radians and ECEF
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    x0, y0, z0 = _geodetic_to_ecef(ref_lat_rad, ref_lon_rad, ref_elev)
    
    # Rotation matrix from ENU to ECEF (transpose of ECEF-to-ENU)
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # Apply inverse rotation to get ECEF offset
    dx = -sin_lon * e - sin_lat * cos_lon * n + cos_lat * cos_lon * u
    dy = cos_lon * e - sin_lat * sin_lon * n + cos_lat * sin_lon * u
    dz = cos_lat * n + sin_lat * u
    
    # Add to reference ECEF position
    x = x0 + dx
    y = y0 + dy
    z = z0 + dz
    
    # Convert back to geodetic
    lat, lon, elevation = _ecef_to_geodetic(x, y, z)
    
    return np.degrees(lat), np.degrees(lon), elevation


def _geodetic_to_ecef(
    lat: FloatOrArray,
    lon: FloatOrArray,
    elevation: FloatOrArray
) -> Tuple[FloatOrArray, FloatOrArray, FloatOrArray]:
    """
    Convert geodetic coordinates to ECEF Cartesian coordinates.
    
    Geodetic coordinates use the WGS84 ellipsoid where:
    - lat: Angle from equatorial plane to point's normal vector
    - lon: Angle from prime meridian to meridian containing point
    - elevation: Distance above ellipsoid surface along normal
    
    ECEF coordinates are Cartesian with origin at Earth's center:
    - X: Intersection of equatorial plane and prime meridian
    - Y: 90° east of X in equatorial plane
    - Z: Through North Pole
    
    Args:
        lat: Latitude in radians
        lon: Longitude in radians
        elevation: Height above ellipsoid in meters
    
    Returns:
        Tuple of (x, y, z) in meters
    """
    # Radius of curvature in the prime vertical (perpendicular to meridian)
    # N = a / sqrt(1 - e² * sin²(lat))
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)
    
    N = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    
    # ECEF coordinates
    # x = (N + elevation) * cos(lat) * cos(lon)
    # y = (N + elevation) * cos(lat) * sin(lon)
    # z = (N * (1 - e²) + elevation) * sin(lat)
    x = (N + elevation) * cos_lat * cos_lon
    y = (N + elevation) * cos_lat * sin_lon
    z = (N * (1.0 - WGS84_E2) + elevation) * sin_lat
    
    return x, y, z


def _ecef_to_geodetic(
    x: FloatOrArray,
    y: FloatOrArray,
    z: FloatOrArray
) -> Tuple[FloatOrArray, FloatOrArray, FloatOrArray]:
    """
    Convert ECEF Cartesian coordinates to geodetic coordinates.
    
    Uses Bowring's iterative method for accurate conversion.
    This is more numerically stable than closed-form solutions.
    
    Args:
        x: ECEF X coordinate in meters
        y: ECEF Y coordinate in meters
        z: ECEF Z coordinate in meters
    
    Returns:
        Tuple of (lat, lon, elevation) where lat/lon are in radians
    """
    # Longitude is straightforward
    lon = np.arctan2(y, x)
    
    # Distance from Z-axis (polar axis)
    p = np.sqrt(x * x + y * y)
    
    # Initial approximation for latitude (Bowring's method)
    theta = np.arctan2(z * WGS84_A, p * WGS84_A * (1.0 - WGS84_E2))
    lat = np.arctan2(
        z + WGS84_E2 * (1.0 - WGS84_E2) * WGS84_A * np.sin(theta)**3 / (1.0 - WGS84_E2),
        p - WGS84_E2 * WGS84_A * np.cos(theta)**3
    )
    
    # One iteration is usually sufficient for meter-level accuracy
    # For higher precision, iterate until convergence
    for _ in range(3):
        sin_lat = np.sin(lat)
        N = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        elevation = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1.0 - WGS84_E2 * N / (N + elevation)))
    
    # Final elevation calculation
    sin_lat = np.sin(lat)
    N = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    elevation = p / np.cos(lat) - N
    
    return lat, lon, elevation


def calculate_azimuth(
    e1: FloatOrArray,
    n1: FloatOrArray,
    e2: FloatOrArray,
    n2: FloatOrArray
) -> FloatOrArray:
    """
    Calculate azimuth angle from point 1 to point 2 in ENU coordinates.
    
    Azimuth is measured clockwise from North (0° = North, 90° = East,
    180° = South, 270° = West). This is the standard convention for
    navigation and satellite tracking.
    
    Geometric derivation:
    - In ENU, North is the positive N-axis
    - East is the positive E-axis
    - Azimuth = atan2(E, N) gives angle from North toward East
    - Result is in range [0, 360) degrees
    
    Args:
        e1: East coordinate of reference point (meters)
        n1: North coordinate of reference point (meters)
        e2: East coordinate of target point (meters)
        n2: North coordinate of target point (meters)
    
    Returns:
        Azimuth angle in degrees [0, 360)
    
    Example:
        >>> az = calculate_azimuth(0, 0, 100, 100)  # NE direction
        >>> print(f"Azimuth: {az:.1f}°")  # Output: 45.0°
    """
    # Compute delta in ENU plane
    de = e2 - e1
    dn = n2 - n1
    
    # atan2(E, N) gives angle from North toward East
    # This matches the navigation convention (clockwise from North)
    azimuth_rad = np.arctan2(de, dn)
    
    # Convert to degrees and normalize to [0, 360)
    azimuth_deg = np.degrees(azimuth_rad)
    azimuth_deg = np.mod(azimuth_deg, 360.0)
    
    return azimuth_deg


def calculate_elevation_angle(
    horizontal_dist: FloatOrArray,
    height_diff: FloatOrArray
) -> FloatOrArray:
    """
    Calculate elevation angle from horizontal distance and height difference.
    
    Elevation angle is measured upward from the horizontal plane.
    Positive angles point above the horizon, negative angles point below.
    
    Geometric derivation:
    - In ENU, the horizontal plane is the E-N plane
    - Elevation = atan2(U, sqrt(E² + N²))
    - This gives angle from horizontal toward zenith
    
    For ray-casting obstruction:
    - Building elevation = atan2(building_height - user_height, distance)
    - Satellite elevation = provided by ephemeris data
    - LOS is clear if: satellite_elevation > building_elevation
    
    Args:
        horizontal_dist: Distance in E-N plane (meters), must be >= 0
        height_diff: Vertical height difference (meters), positive = target above reference
    
    Returns:
        Elevation angle in degrees, range [-90, 90]
    
    Example:
        >>> el = calculate_elevation_angle(100, 50)  # 50m up at 100m distance
        >>> print(f"Elevation: {el:.1f}°")  # Output: 26.6°
    """
    # Ensure horizontal distance is non-negative
    horizontal_dist = np.maximum(horizontal_dist, 1e-10)  # Avoid division by zero
    
    # atan2(height, distance) gives angle from horizontal
    elevation_rad = np.arctan2(height_diff, horizontal_dist)
    elevation_deg = np.degrees(elevation_rad)
    
    return elevation_deg


def azimuth_to_sector_index(azimuth: FloatOrArray, sector_width: float = 2.0) -> np.ndarray:
    """
    Convert azimuth angle to sector index for obstruction profile.
    
    The obstruction profile divides the full 360° into sectors of equal width.
    Each sector stores the maximum obstruction elevation for that azimuth range.
    
    For 2° sectors (default):
    - Sector 0: 0° to 2° (centered at 1°)
    - Sector 1: 2° to 4° (centered at 3°)
    - ...
    - Sector 179: 358° to 360°/0° (centered at 359°)
    
    Args:
        azimuth: Azimuth angle(s) in degrees [0, 360)
        sector_width: Width of each sector in degrees (default 2°)
    
    Returns:
        Sector index(es) as integer array [0, n_sectors-1]
    
    Example:
        >>> idx = azimuth_to_sector_index(45.0)  # Returns 22 (45/2 = 22.5 -> 22)
    """
    # Normalize azimuth to [0, 360)
    azimuth = np.mod(azimuth, 360.0)
    
    # Calculate sector index
    # Floor division gives the sector containing this azimuth
    sector_idx = np.floor(azimuth / sector_width).astype(np.int32)
    
    # Clamp to valid range (handles azimuth = 360 exactly)
    n_sectors = int(360.0 / sector_width)
    sector_idx = np.clip(sector_idx, 0, n_sectors - 1)
    
    return sector_idx


def sector_index_to_azimuth(sector_idx: int, sector_width: float = 2.0) -> float:
    """
    Convert sector index to representative azimuth angle.
    
    Returns the center azimuth of the specified sector.
    
    Args:
        sector_idx: Sector index [0, n_sectors-1]
        sector_width: Width of each sector in degrees (default 2°)
    
    Returns:
        Center azimuth of the sector in degrees
    
    Example:
        >>> az = sector_index_to_azimuth(22)  # Returns 45.0 (center of sector 22)
    """
    return sector_idx * sector_width + sector_width / 2.0


def calculate_horizontal_distance(
    e1: FloatOrArray,
    n1: FloatOrArray,
    e2: FloatOrArray,
    n2: FloatOrArray
) -> FloatOrArray:
    """
    Calculate horizontal (E-N plane) distance between two points.
    
    Args:
        e1: East coordinate of point 1 (meters)
        n1: North coordinate of point 1 (meters)
        e2: East coordinate of point 2 (meters)
        n2: North coordinate of point 2 (meters)
    
    Returns:
        Horizontal distance in meters
    """
    de = e2 - e1
    dn = n2 - n1
    return np.sqrt(de * de + dn * dn)


def calculate_3d_distance(
    e1: FloatOrArray,
    n1: FloatOrArray,
    u1: FloatOrArray,
    e2: FloatOrArray,
    n2: FloatOrArray,
    u2: FloatOrArray
) -> FloatOrArray:
    """
    Calculate 3D Euclidean distance between two points in ENU.
    
    Args:
        e1, n1, u1: ENU coordinates of point 1 (meters)
        e2, n2, u2: ENU coordinates of point 2 (meters)
    
    Returns:
        3D distance in meters
    """
    de = e2 - e1
    dn = n2 - n1
    du = u2 - u1
    return np.sqrt(de * de + dn * dn + du * du)


def is_within_radius(
    e: FloatOrArray,
    n: FloatOrArray,
    radius: float
) -> np.ndarray:
    """
    Check if points are within a given horizontal radius.
    
    Args:
        e: East coordinate(s) (meters)
        n: North coordinate(s) (meters)
        radius: Maximum horizontal distance (meters)
    
    Returns:
        Boolean array indicating which points are within radius
    """
    dist_sq = e * e + n * n
    return dist_sq <= radius * radius


# Precompute constants for performance
_DEG_TO_RAD = np.pi / 180.0
_RAD_TO_DEG = 180.0 / np.pi
