"""Coordinate utilities package for LinkSpot.

This package provides coordinate transformation utilities for the LinkSpot
application, focusing on ENU (East-North-Up) local tangent plane coordinates
for geometric calculations.

Main Components:
- enu_transforms: WGS84 to ENU coordinate conversions
- azimuth_elevation: Azimuth and elevation angle calculations
- geohash_utils: Geohash encoding/decoding for spatial caching

Usage:
    from coordinates import wgs84_to_enu, calculate_azimuth, encode_geohash
    
    # Convert WGS84 to ENU
    e, n, u = wgs84_to_enu(lat, lon, elev, ref_lat, ref_lon, ref_elev)
    
    # Calculate azimuth between two points
    azimuth = calculate_azimuth(e1, n1, e2, n2)
    
    # Encode location to geohash
    geohash = encode_geohash(lat, lon, precision=6)

Coordinate System Conventions:
- WGS84: (latitude, longitude, elevation) in degrees and meters
- ENU: (east, north, up) in meters from reference point
- Azimuth: 0° = North, 90° = East, 180° = South, 270° = West
- Elevation: 0° = horizon, 90° = zenith (straight up)

License: BSD License
Version: 1.0.0
"""

# ENU transformation functions
from .enu_transforms import (
    wgs84_to_enu,
    enu_to_wgs84,
    wgs84_to_enu_vectorized,
    enu_to_wgs84_vectorized,
    get_enu_rotation_matrix,
    WGS84_A,
    WGS84_F,
    WGS84_E2,
)

# Azimuth and elevation functions
from .azimuth_elevation import (
    calculate_azimuth,
    calculate_azimuth_vectorized,
    calculate_elevation_angle,
    calculate_elevation_from_enu,
    azimuth_to_sector,
    sector_to_azimuth_range,
    calculate_3d_distance,
    calculate_horizontal_distance,
    get_cardinal_direction,
    calculate_line_of_sight_vector,
)

# Geohash utility functions
from .geohash_utils import (
    encode_geohash,
    decode_geohash,
    decode_geohash_center,
    get_geohash_bounds,
    get_geohash_dimensions,
    get_geohashes_in_radius,
    get_neighbors,
    haversine_distance,
    get_geohash_precision_for_radius,
    expand_geohash_prefix,
    are_geohashes_adjacent,
    get_parent_geohash,
    get_common_prefix,
    GEOHASH_CHARS,
    GEOHASH_DIMENSIONS,
)

__version__ = "1.0.0"
__author__ = "LinkSpot Team"
__license__ = "BSD License"

# Define what gets imported with 'from coordinates import *'
__all__ = [
    # ENU transforms
    'wgs84_to_enu',
    'enu_to_wgs84',
    'wgs84_to_enu_vectorized',
    'enu_to_wgs84_vectorized',
    'get_enu_rotation_matrix',
    'WGS84_A',
    'WGS84_F',
    'WGS84_E2',
    
    # Azimuth and elevation
    'calculate_azimuth',
    'calculate_azimuth_vectorized',
    'calculate_elevation_angle',
    'calculate_elevation_from_enu',
    'azimuth_to_sector',
    'sector_to_azimuth_range',
    'calculate_3d_distance',
    'calculate_horizontal_distance',
    'get_cardinal_direction',
    'calculate_line_of_sight_vector',
    
    # Geohash utilities
    'encode_geohash',
    'decode_geohash',
    'decode_geohash_center',
    'get_geohash_bounds',
    'get_geohash_dimensions',
    'get_geohashes_in_radius',
    'get_neighbors',
    'haversine_distance',
    'get_geohash_precision_for_radius',
    'expand_geohash_prefix',
    'are_geohashes_adjacent',
    'get_parent_geohash',
    'get_common_prefix',
    'GEOHASH_CHARS',
    'GEOHASH_DIMENSIONS',
]
