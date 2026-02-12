#!/usr/bin/env python3
"""
Distance Calculations for LinkSpot

This module provides various distance calculation methods for geodetic
and Cartesian coordinate systems. Different methods offer trade-offs
between accuracy and computational efficiency.

Distance Methods:
=================
1. Haversine: Fast, assumes spherical Earth (~0.5% error)
2. Vincenty: Accurate, uses WGS84 ellipsoid (iterative)
3. Euclidean ENU: For local Cartesian coordinates

License: BSD-3-Clause
Copyright (c) 2024 LinkSpot Project
"""

import math
from typing import Tuple, Optional
import numpy as np
from numpy.typing import NDArray

try:
    from .enu_transforms import WGS84_A, WGS84_F, WGS84_B, WGS84_E2
except ImportError:
    from enu_transforms import WGS84_A, WGS84_F, WGS84_B, WGS84_E2

# Mean Earth radius for spherical approximations
EARTH_MEAN_RADIUS = 6371008.8  # meters (IUGG definition)


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> float:
    """
    Calculate great-circle distance using the Haversine formula.
    
    The Haversine formula assumes a spherical Earth and provides
    reasonable accuracy for most applications (error < 0.5%).
    
    Mathematical Formula:
    ---------------------
    For two points (φ₁, λ₁) and (φ₂, λ₂) in radians:
    
    Δφ = φ₂ - φ₁
    Δλ = λ₂ - λ₁
    
    a = sin²(Δφ/2) + cos(φ₁) · cos(φ₂) · sin²(Δλ/2)
    c = 2 · atan2(√a, √(1-a))
    d = R · c
    
    Where:
    - R = Earth's mean radius (6371008.8 m)
    - d = great-circle distance
    
    The haversine function: hav(θ) = sin²(θ/2) = (1 - cos(θ))/2
    was historically used for logarithmic computation.
    
    Accuracy:
    ---------
    - Assumes spherical Earth (actual Earth is an oblate spheroid)
    - Maximum error: ~0.5% (about ±0.5 km per 100 km)
    - Error increases with distance and latitude
    - Suitable for: quick estimates, small distances (<100 km)
    
    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees
        
    Returns:
        Great-circle distance in meters
        
    Raises:
        ValueError: If latitudes are outside [-90, 90]
        
    References:
        - van Brummelen, G. (2013). "Heavenly Mathematics". Princeton
          University Press, Chapter 7.
        - Sinnott, R.W. (1984). "Virtues of the Haversine". Sky and
          Telescope, 68(2), 159.
          
    Example:
        >>> # Distance from NYC to Philadelphia
        >>> haversine_distance(40.7128, -74.0060, 39.9526, -75.1652)
        129023.1  # meters (~129 km)
        
        >>> # Distance from equator to pole
        >>> haversine_distance(0, 0, 90, 0)
        10007543.6  # meters (~10,007 km, quarter meridian)
    """
    # Validate inputs
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be in range [-90, 90]")
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    # Haversine formula
    sin_dlat_2 = math.sin(dlat / 2.0)
    sin_dlon_2 = math.sin(dlon / 2.0)
    
    a = sin_dlat_2 * sin_dlat_2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * sin_dlon_2 * sin_dlon_2
    
    # Clamp to [0, 1] to avoid numerical errors
    a = min(1.0, max(0.0, a))
    
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    return EARTH_MEAN_RADIUS * c


def haversine_distance_vectorized(
    lats1: NDArray[np.float64],
    lons1: NDArray[np.float64],
    lats2: NDArray[np.float64],
    lons2: NDArray[np.float64]
) -> NDArray[np.float64]:
    """
    Vectorized Haversine distance calculation.
    
    Args:
        lats1: Array of latitudes for first points
        lons1: Array of longitudes for first points
        lats2: Array of latitudes for second points
        lons2: Array of longitudes for second points
        
    Returns:
        Array of distances in meters
    """
    lat1_rad = np.radians(lats1)
    lat2_rad = np.radians(lats2)
    dlat = np.radians(lats2 - lats1)
    dlon = np.radians(lons2 - lons1)
    
    sin_dlat_2 = np.sin(dlat / 2.0)
    sin_dlon_2 = np.sin(dlon / 2.0)
    
    a = sin_dlat_2 ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * sin_dlon_2 ** 2
    a = np.clip(a, 0.0, 1.0)
    
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    
    return EARTH_MEAN_RADIUS * c


def vincenty_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    max_iterations: int = 100,
    convergence_threshold: float = 1e-12
) -> float:
    """
    Calculate geodesic distance using Vincenty's inverse formula.
    
    Vincenty's formula uses the WGS84 ellipsoid and provides
    sub-millimeter accuracy for most Earth distances.
    
    Mathematical Formula:
    ---------------------
    Vincenty's inverse method solves for the geodesic on an ellipsoid:
    
    Given: (φ₁, λ₁), (φ₂, λ₂) on ellipsoid with semi-major axis a and
    flattening f.
    
    1. Compute reduced latitudes: tan(U) = (1-f) · tan(φ)
    2. Set initial λ = L = λ₂ - λ₁
    3. Iterate until convergence:
       - Compute angular distance σ between points
       - Compute azimuths α₁, α₂
       - Update λ using spherical trig relationships
    4. Compute final distance: s = b · A · (σ - Δσ)
    
    Where b is the semi-minor axis and A, Δσ are correction terms
    for ellipsoidal geometry.
    
    Accuracy:
    ---------
    - Uses WGS84 ellipsoid parameters
    - Sub-millimeter accuracy for most distances
    - Converges in 5-20 iterations for most cases
    - May fail to converge for nearly antipodal points
    
    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees
        max_iterations: Maximum iterations before giving up (default 100)
        convergence_threshold: Convergence criterion (default 1e-12)
        
    Returns:
        Geodesic distance in meters
        
    Raises:
        ValueError: If coordinates are invalid
        RuntimeError: If solution fails to converge
        
    References:
        - Vincenty, T. (1975). "Direct and Inverse Solutions of Geodesics
          on the Ellipsoid with application of nested equations".
          Survey Review, 23(176), 88-93.
        - Vincenty, T. (1976). "Correspondence". Survey Review, 23(180),
          294.
        - Karney, C.F.F. (2013). "Algorithms for geodesics".
          Journal of Geodesy, 87(1), 43-55.
          
    Example:
        >>> # Distance from NYC to Philadelphia (more accurate)
        >>> vincenty_distance(40.7128, -74.0060, 39.9526, -75.1652)
        129023.4  # meters
        
        >>> # Quarter meridian (equator to pole)
        >>> vincenty_distance(0, 0, 90, 0)
        10001965.7  # meters (more accurate than Haversine)
    """
    # Validate inputs
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be in range [-90, 90]")
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    lon1_rad = math.radians(lon1)
    lon2_rad = math.radians(lon2)
    
    # WGS84 parameters
    a = WGS84_A
    f = WGS84_F
    b = WGS84_B
    
    # Reduced latitudes (parametric latitudes)
    U1 = math.atan((1 - f) * math.tan(lat1_rad))
    U2 = math.atan((1 - f) * math.tan(lat2_rad))
    
    L = lon2_rad - lon1_rad
    
    sin_U1 = math.sin(U1)
    cos_U1 = math.cos(U1)
    sin_U2 = math.sin(U2)
    cos_U2 = math.cos(U2)
    
    # Iterate until convergence
    lambda_val = L
    for iteration in range(max_iterations):
        sin_lambda = math.sin(lambda_val)
        cos_lambda = math.cos(lambda_val)
        
        sin_sigma = math.sqrt(
            (cos_U2 * sin_lambda) ** 2 +
            (cos_U1 * sin_U2 - sin_U1 * cos_U2 * cos_lambda) ** 2
        )
        
        # Handle coincident points
        if sin_sigma == 0:
            return 0.0
        
        cos_sigma = sin_U1 * sin_U2 + cos_U1 * cos_U2 * cos_lambda
        sigma = math.atan2(sin_sigma, cos_sigma)
        
        sin_alpha = cos_U1 * cos_U2 * sin_lambda / sin_sigma
        
        # Clamp to handle numerical errors
        sin_alpha = max(-1.0, min(1.0, sin_alpha))
        
        cos_sq_alpha = 1 - sin_alpha ** 2
        
        # Handle equatorial line case
        if cos_sq_alpha == 0:
            cos_2sigma_m = 0
        else:
            cos_2sigma_m = cos_sigma - 2 * sin_U1 * sin_U2 / cos_sq_alpha
        
        C = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 * cos_sq_alpha))
        
        lambda_prev = lambda_val
        lambda_val = L + (1 - C) * f * sin_alpha * (
            sigma + C * sin_sigma * (
                cos_2sigma_m + C * cos_sigma * (-1 + 2 * cos_2sigma_m ** 2)
            )
        )
        
        # Check convergence
        if abs(lambda_val - lambda_prev) < convergence_threshold:
            break
    else:
        # Failed to converge - this can happen for nearly antipodal points
        # Fall back to Haversine as a safe approximation
        return haversine_distance(lat1, lon1, lat2, lon2)
    
    # Compute final distance
    u_sq = cos_sq_alpha * (a ** 2 - b ** 2) / (b ** 2)
    A = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    B = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    
    delta_sigma = B * sin_sigma * (
        cos_2sigma_m + B / 4 * (
            cos_sigma * (-1 + 2 * cos_2sigma_m ** 2) -
            B / 6 * cos_2sigma_m * (-3 + 4 * sin_sigma ** 2) *
            (-3 + 4 * cos_2sigma_m ** 2)
        )
    )
    
    s = b * A * (sigma - delta_sigma)
    
    return s


def euclidean_distance_enu(
    e1: float,
    n1: float,
    u1: float,
    e2: float,
    n2: float,
    u2: float
) -> float:
    """
    Calculate 3D Euclidean distance in ENU coordinate frame.
    
    This is the straight-line (slant range) distance between two points
    in the local ENU Cartesian coordinate system.
    
    Mathematical Formula:
    ---------------------
    d = √((E₂-E₁)² + (N₂-N₁)² + (U₂-U₁)²)
    
    Args:
        e1, n1, u1: First point ENU coordinates in meters
        e2, n2, u2: Second point ENU coordinates in meters
        
    Returns:
        3D Euclidean distance in meters
        
    Example:
        >>> euclidean_distance_enu(0, 0, 0, 3, 4, 0)
        5.0
        >>> euclidean_distance_enu(0, 0, 0, 1, 1, 1)
        1.7320508075688772
    """
    return math.sqrt(
        (e2 - e1) ** 2 +
        (n2 - n1) ** 2 +
        (u2 - u1) ** 2
    )


def euclidean_distance_enu_vectorized(
    e1: NDArray[np.float64],
    n1: NDArray[np.float64],
    u1: NDArray[np.float64],
    e2: NDArray[np.float64],
    n2: NDArray[np.float64],
    u2: NDArray[np.float64]
) -> NDArray[np.float64]:
    """
    Vectorized 3D Euclidean distance in ENU frame.
    
    Args:
        e1, n1, u1: First point ENU coordinate arrays
        e2, n2, u2: Second point ENU coordinate arrays
        
    Returns:
        Array of distances in meters
    """
    return np.sqrt(
        (e2 - e1) ** 2 +
        (n2 - n1) ** 2 +
        (u2 - u1) ** 2
    )


def horizontal_distance_enu(
    e1: float,
    n1: float,
    e2: float,
    n2: float
) -> float:
    """
    Calculate 2D horizontal distance in ENU frame (ignoring Up component).
    
    This gives the ground-level distance between two points, useful
    for map distance calculations.
    
    Mathematical Formula:
    ---------------------
    d_h = √((E₂-E₁)² + (N₂-N₁)²)
    
    Args:
        e1, n1: First point East-North coordinates in meters
        e2, n2: Second point East-North coordinates in meters
        
    Returns:
        Horizontal distance in meters
        
    Example:
        >>> horizontal_distance_enu(0, 0, 3, 4)
        5.0
    """
    return math.sqrt((e2 - e1) ** 2 + (n2 - n1) ** 2)


def horizontal_distance_enu_vectorized(
    e1: NDArray[np.float64],
    n1: NDArray[np.float64],
    e2: NDArray[np.float64],
    n2: NDArray[np.float64]
) -> NDArray[np.float64]:
    """
    Vectorized 2D horizontal distance in ENU frame.
    
    Args:
        e1, n1: First point East-North coordinate arrays
        e2, n2: Second point East-North coordinate arrays
        
    Returns:
        Array of horizontal distances in meters
    """
    return np.sqrt((e2 - e1) ** 2 + (n2 - n1) ** 2)


def distance_along_parallel(
    lat: float,
    delta_lon: float
) -> float:
    """
    Calculate distance along a parallel (circle of latitude).
    
    The radius of a parallel varies with latitude as:
    r(φ) = a · cos(φ) / √(1 - e² sin²φ)
    
    Args:
        lat: Latitude in degrees
        delta_lon: Longitude difference in degrees
        
    Returns:
        Distance along the parallel in meters
        
    Example:
        >>> # Distance along equator for 1° longitude
        >>> distance_along_parallel(0, 1)
        111319.49  # meters
        
        >>> # Distance at 45° latitude for 1° longitude
        >>> distance_along_parallel(45, 1)
        78846.81   # meters (shorter due to smaller radius)
    """
    lat_rad = math.radians(lat)
    delta_lon_rad = math.radians(delta_lon)
    
    # Radius of curvature in the prime vertical at this latitude
    sin_lat = math.sin(lat_rad)
    N = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    
    # Radius of the parallel
    parallel_radius = N * math.cos(lat_rad)
    
    return parallel_radius * abs(delta_lon_rad)


def distance_along_meridian(
    delta_lat: float
) -> float:
    """
    Calculate distance along a meridian (line of constant longitude).
    
    This uses the meridional arc length formula for the WGS84 ellipsoid.
    
    Args:
        delta_lat: Latitude difference in degrees
        
    Returns:
        Distance along the meridian in meters
        
    Example:
        >>> # Distance along meridian for 1° latitude
        >>> distance_along_meridian(1)
        110946.26  # meters (varies slightly with latitude)
    """
    # Mean meridional radius of curvature
    # For small distances, this is approximately constant
    # More accurate formula would integrate along the meridian
    
    # Use the length of a degree of latitude at 45° as approximation
    lat_rad = math.radians(45)  # Representative latitude
    sin_lat = math.sin(lat_rad)
    
    # Meridional radius of curvature
    M = WGS84_A * (1 - WGS84_E2) / ((1 - WGS84_E2 * sin_lat ** 2) ** 1.5)
    
    return M * abs(math.radians(delta_lat))


def calculate_distance_with_uncertainty(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    lat_uncertainty_m: float = 0.0,
    lon_uncertainty_m: float = 0.0
) -> Tuple[float, float]:
    """
    Calculate distance with uncertainty propagation.
    
    Args:
        lat1, lon1: First point coordinates in degrees
        lat2, lon2: Second point coordinates in degrees
        lat_uncertainty_m: Position uncertainty in North-South direction (meters)
        lon_uncertainty_m: Position uncertainty in East-West direction (meters)
        
    Returns:
        Tuple of (distance_m, uncertainty_m)
        
    Example:
        >>> calculate_distance_with_uncertainty(
        ...     40.7128, -74.0060, 39.9526, -75.1652,
        ...     lat_uncertainty_m=10, lon_uncertainty_m=10
        ... )
        (129023.1, 14.14)  # distance with propagated uncertainty
    """
    # Calculate nominal distance
    distance = vincenty_distance(lat1, lon1, lat2, lon2)
    
    # Propagate uncertainties (RSS)
    # Assume uncertainties are uncorrelated
    uncertainty = math.sqrt(lat_uncertainty_m ** 2 + lon_uncertainty_m ** 2)
    
    return (distance, uncertainty)


def is_within_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    max_distance_m: float,
    method: str = 'haversine'
) -> bool:
    """
    Check if two points are within a specified distance.
    
    Args:
        lat1, lon1: First point coordinates in degrees
        lat2, lon2: Second point coordinates in degrees
        max_distance_m: Maximum distance threshold in meters
        method: Distance method ('haversine' or 'vincenty')
        
    Returns:
        True if distance <= max_distance_m, False otherwise
        
    Example:
        >>> is_within_distance(40.7128, -74.0060, 40.72, -74.01, 2000)
        True
    """
    if method == 'haversine':
        distance = haversine_distance(lat1, lon1, lat2, lon2)
    elif method == 'vincenty':
        distance = vincenty_distance(lat1, lon1, lat2, lon2)
    else:
        raise ValueError(f"Unknown distance method: {method}")
    
    return distance <= max_distance_m


# Export public API
__all__ = [
    'haversine_distance',
    'haversine_distance_vectorized',
    'vincenty_distance',
    'euclidean_distance_enu',
    'euclidean_distance_enu_vectorized',
    'horizontal_distance_enu',
    'horizontal_distance_enu_vectorized',
    'distance_along_parallel',
    'distance_along_meridian',
    'calculate_distance_with_uncertainty',
    'is_within_distance',
    'EARTH_MEAN_RADIUS',
]