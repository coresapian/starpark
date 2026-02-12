"""ENU coordinate transformations. BSD License.

This module provides conversions between WGS84 (lat, lon, elevation) and
ENU (East-North-Up) local tangent plane coordinates.

ENU Coordinate System:
- Origin: Reference point (ref_lat, ref_lon, ref_elev)
- E (East): Positive towards East (tangent to local parallel)
- N (North): Positive towards North (tangent to local meridian)
- U (Up): Positive away from Earth's center (radial/up direction)

All distances are in meters.
"""

import numpy as np
from typing import Tuple, Union
import pyproj

# WGS84 ellipsoid parameters
WGS84_A = 6378137.0  # Semi-major axis (meters)
WGS84_F = 1 / 298.257223563  # Flattening
WGS84_E2 = 2 * WGS84_F - WGS84_F ** 2  # First eccentricity squared


def wgs84_to_enu(
    lat: float, 
    lon: float, 
    elevation: float,
    ref_lat: float, 
    ref_lon: float, 
    ref_elev: float
) -> Tuple[float, float, float]:
    """Convert WGS84 geodetic coordinates to ENU local tangent plane coordinates.
    
    Args:
        lat: Target latitude in degrees (-90 to 90)
        lon: Target longitude in degrees (-180 to 180)
        elevation: Target elevation in meters above WGS84 ellipsoid
        ref_lat: Reference point latitude in degrees (ENU origin)
        ref_lon: Reference point longitude in degrees (ENU origin)
        ref_elev: Reference point elevation in meters (ENU origin)
    
    Returns:
        Tuple of (e, n, u) coordinates in meters from reference point:
        - e: East coordinate (positive = East)
        - n: North coordinate (positive = North)  
        - u: Up coordinate (positive = Up/above reference)
    
    Example:
        >>> # User at Seattle, looking at a point 100m East, 50m North
        >>> e, n, u = wgs84_to_enu(47.6062, -122.3321, 50.0, 
        ...                        47.6062, -122.3321, 0.0)
        >>> print(f"E: {e:.1f}m, N: {n:.1f}m, U: {u:.1f}m")
    """
    # Convert lat/lon to radians
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    # Calculate radii of curvature
    # Radius of curvature in the prime vertical (perpendicular to meridian)
    N_ref = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(ref_lat_rad) ** 2)
    N_target = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
    
    # Convert geodetic to ECEF (Earth-Centered, Earth-Fixed) coordinates
    # ECEF: Origin at Earth's center, X towards 0°N 0°E, Z towards North Pole
    
    # Reference point ECEF
    ref_x = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.cos(ref_lon_rad)
    ref_y = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.sin(ref_lon_rad)
    ref_z = (N_ref * (1 - WGS84_E2) + ref_elev) * np.sin(ref_lat_rad)
    
    # Target point ECEF
    target_x = (N_target + elevation) * np.cos(lat_rad) * np.cos(lon_rad)
    target_y = (N_target + elevation) * np.cos(lat_rad) * np.sin(lon_rad)
    target_z = (N_target * (1 - WGS84_E2) + elevation) * np.sin(lat_rad)
    
    # Delta in ECEF frame
    dx = target_x - ref_x
    dy = target_y - ref_y
    dz = target_z - ref_z
    
    # Rotation matrix from ECEF to ENU
    # ENU frame: East (tangent to parallel), North (tangent to meridian), Up (radial)
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # Rotation matrix elements
    # [ -sin_lon          cos_lon          0      ] [dx]   [e]
    # [ -sin_lat*cos_lon  -sin_lat*sin_lon  cos_lat] [dy] = [n]
    # [  cos_lat*cos_lon   cos_lat*sin_lon  sin_lat] [dz]   [u]
    
    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    
    return (float(e), float(n), float(u))


def enu_to_wgs84(
    e: float, 
    n: float, 
    u: float,
    ref_lat: float, 
    ref_lon: float, 
    ref_elev: float
) -> Tuple[float, float, float]:
    """Convert ENU local tangent plane coordinates back to WGS84.
    
    Args:
        e: East coordinate in meters from reference point
        n: North coordinate in meters from reference point
        u: Up coordinate in meters from reference point
        ref_lat: Reference point latitude in degrees (ENU origin)
        ref_lon: Reference point longitude in degrees (ENU origin)
        ref_elev: Reference point elevation in meters (ENU origin)
    
    Returns:
        Tuple of (lat, lon, elevation) in degrees and meters:
        - lat: Latitude in degrees (-90 to 90)
        - lon: Longitude in degrees (-180 to 180)
        - elevation: Elevation in meters above WGS84 ellipsoid
    
    Example:
        >>> # Convert ENU offset back to WGS84
        >>> lat, lon, elev = enu_to_wgs84(100.0, 50.0, 20.0,
        ...                               47.6062, -122.3321, 0.0)
        >>> print(f"Lat: {lat:.6f}°, Lon: {lon:.6f}°, Elev: {elev:.1f}m")
    """
    # Convert reference lat/lon to radians
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    # Calculate radius of curvature at reference point
    N_ref = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(ref_lat_rad) ** 2)
    
    # Reference point ECEF
    ref_x = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.cos(ref_lon_rad)
    ref_y = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.sin(ref_lon_rad)
    ref_z = (N_ref * (1 - WGS84_E2) + ref_elev) * np.sin(ref_lat_rad)
    
    # Rotation matrix from ENU to ECEF (inverse of ECEF-to-ENU)
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # ENU to ECEF rotation (transpose of ECEF-to-ENU)
    dx = -sin_lon * e - sin_lat * cos_lon * n + cos_lat * cos_lon * u
    dy = cos_lon * e - sin_lat * sin_lon * n + cos_lat * sin_lon * u
    dz = cos_lat * n + sin_lat * u
    
    # Target point ECEF
    target_x = ref_x + dx
    target_y = ref_y + dy
    target_z = ref_z + dz
    
    # Convert ECEF to geodetic (lat, lon, elevation)
    # Using iterative method for accuracy
    
    # Longitude is straightforward
    lon = np.degrees(np.arctan2(target_y, target_x))
    
    # Latitude and elevation require iteration
    p = np.sqrt(target_x ** 2 + target_y ** 2)
    
    # Initial guess for latitude
    lat = np.degrees(np.arctan2(target_z, p * (1 - WGS84_E2)))
    
    # Iterate to refine (typically converges in 2-3 iterations)
    for _ in range(5):
        lat_rad = np.radians(lat)
        N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
        elevation = p / np.cos(lat_rad) - N
        lat_new = np.degrees(np.arctan2(target_z, p * (1 - WGS84_E2 * N / (N + elevation))))
        if abs(lat_new - lat) < 1e-12:
            break
        lat = lat_new
    
    # Final elevation calculation
    lat_rad = np.radians(lat)
    N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
    elevation = p / np.cos(lat_rad) - N
    
    return (float(lat), float(lon), float(elevation))


def wgs84_to_enu_vectorized(
    lats: np.ndarray, 
    lons: np.ndarray, 
    elevations: np.ndarray,
    ref_lat: float, 
    ref_lon: float, 
    ref_elev: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized WGS84 to ENU conversion for multiple points.
    
    This is significantly faster than calling wgs84_to_enu() in a loop
    for large arrays of points.
    
    Args:
        lats: Array of latitudes in degrees
        lons: Array of longitudes in degrees
        elevations: Array of elevations in meters
        ref_lat: Reference point latitude in degrees (ENU origin)
        ref_lon: Reference point longitude in degrees (ENU origin)
        ref_elev: Reference point elevation in meters (ENU origin)
    
    Returns:
        Tuple of (e_array, n_array, u_array) as numpy arrays in meters
    
    Example:
        >>> import numpy as np
        >>> lats = np.array([47.6062, 47.6070, 47.6050])
        >>> lons = np.array([-122.3321, -122.3310, -122.3330])
        >>> elevs = np.array([10.0, 20.0, 15.0])
        >>> e, n, u = wgs84_to_enu_vectorized(lats, lons, elevs,
        ...                                   47.6062, -122.3321, 0.0)
    """
    # Ensure numpy arrays
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    elevations = np.asarray(elevations, dtype=np.float64)
    
    # Convert reference point to radians
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    # Convert all target points to radians
    lat_rad = np.radians(lats)
    lon_rad = np.radians(lons)
    
    # Calculate radii of curvature
    N_ref = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(ref_lat_rad) ** 2)
    N_target = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
    
    # Reference point ECEF (scalar)
    ref_x = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.cos(ref_lon_rad)
    ref_y = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.sin(ref_lon_rad)
    ref_z = (N_ref * (1 - WGS84_E2) + ref_elev) * np.sin(ref_lat_rad)
    
    # Target points ECEF (arrays)
    target_x = (N_target + elevations) * np.cos(lat_rad) * np.cos(lon_rad)
    target_y = (N_target + elevations) * np.cos(lat_rad) * np.sin(lon_rad)
    target_z = (N_target * (1 - WGS84_E2) + elevations) * np.sin(lat_rad)
    
    # Delta in ECEF
    dx = target_x - ref_x
    dy = target_y - ref_y
    dz = target_z - ref_z
    
    # Rotation matrix elements (scalars)
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # Apply rotation to all points
    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    
    return (e, n, u)


def enu_to_wgs84_vectorized(
    e: np.ndarray, 
    n: np.ndarray, 
    u: np.ndarray,
    ref_lat: float, 
    ref_lon: float, 
    ref_elev: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized ENU to WGS84 conversion for multiple points.
    
    Args:
        e: Array of East coordinates in meters
        n: Array of North coordinates in meters
        u: Array of Up coordinates in meters
        ref_lat: Reference point latitude in degrees (ENU origin)
        ref_lon: Reference point longitude in degrees (ENU origin)
        ref_elev: Reference point elevation in meters (ENU origin)
    
    Returns:
        Tuple of (lat_array, lon_array, elevation_array)
    """
    # Ensure numpy arrays
    e = np.asarray(e, dtype=np.float64)
    n = np.asarray(n, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    
    # Convert reference to radians
    ref_lat_rad = np.radians(ref_lat)
    ref_lon_rad = np.radians(ref_lon)
    
    # Reference ECEF
    N_ref = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(ref_lat_rad) ** 2)
    ref_x = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.cos(ref_lon_rad)
    ref_y = (N_ref + ref_elev) * np.cos(ref_lat_rad) * np.sin(ref_lon_rad)
    ref_z = (N_ref * (1 - WGS84_E2) + ref_elev) * np.sin(ref_lat_rad)
    
    # Rotation elements
    sin_lat = np.sin(ref_lat_rad)
    cos_lat = np.cos(ref_lat_rad)
    sin_lon = np.sin(ref_lon_rad)
    cos_lon = np.cos(ref_lon_rad)
    
    # ENU to ECEF
    dx = -sin_lon * e - sin_lat * cos_lon * n + cos_lat * cos_lon * u
    dy = cos_lon * e - sin_lat * sin_lon * n + cos_lat * sin_lon * u
    dz = cos_lat * n + sin_lat * u
    
    # Target ECEF
    target_x = ref_x + dx
    target_y = ref_y + dy
    target_z = ref_z + dz
    
    # ECEF to geodetic
    lon = np.degrees(np.arctan2(target_y, target_x))
    p = np.sqrt(target_x ** 2 + target_y ** 2)
    
    # Iterative latitude/elevation calculation
    lat = np.degrees(np.arctan2(target_z, p * (1 - WGS84_E2)))
    
    for _ in range(5):
        lat_rad = np.radians(lat)
        N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
        elevation = p / np.cos(lat_rad) - N
        lat_new = np.degrees(np.arctan2(target_z, p * (1 - WGS84_E2 * N / (N + elevation))))
        lat = lat_new
    
    # Final elevation
    lat_rad = np.radians(lat)
    N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat_rad) ** 2)
    elevation = p / np.cos(lat_rad) - N
    
    return (lat, lon, elevation)


def get_enu_rotation_matrix(ref_lat: float, ref_lon: float) -> np.ndarray:
    """Get the 3x3 rotation matrix from ECEF to ENU.
    
    Useful for transforming vectors (e.g., velocity) between frames.
    
    Args:
        ref_lat: Reference latitude in degrees
        ref_lon: Reference longitude in degrees
    
    Returns:
        3x3 numpy array rotation matrix R where [e,n,u]^T = R @ [dx,dy,dz]^T
    """
    lat_rad = np.radians(ref_lat)
    lon_rad = np.radians(ref_lon)
    
    sin_lat = np.sin(lat_rad)
    cos_lat = np.cos(lat_rad)
    sin_lon = np.sin(lon_rad)
    cos_lon = np.cos(lon_rad)
    
    # Rotation matrix from ECEF to ENU
    R = np.array([
        [-sin_lon,           cos_lon,           0      ],
        [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
        [ cos_lat * cos_lon,  cos_lat * sin_lon, sin_lat]
    ])
    
    return R
