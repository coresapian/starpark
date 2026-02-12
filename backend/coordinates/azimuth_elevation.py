"""Azimuth and elevation calculations. BSD License.

This module provides calculations for azimuth (bearing) and elevation angles
in the ENU (East-North-Up) local tangent plane coordinate system.

Azimuth Convention:
- 0° = North (positive N direction)
- 90° = East (positive E direction)
- 180° = South (negative N direction)
- 270° = West (negative E direction)

Elevation Convention:
- 0° = Horizon (horizontal plane)
- 90° = Zenith (straight up)
- Negative values = below horizon
"""

import numpy as np
from typing import Tuple, Union


def calculate_azimuth(e1: float, n1: float, e2: float, n2: float) -> float:
    """Calculate azimuth from point 1 to point 2 in ENU frame.
    
    The azimuth is the horizontal angle measured clockwise from North.
    
    Args:
        e1: East coordinate of point 1 in meters
        n1: North coordinate of point 1 in meters
        e2: East coordinate of point 2 in meters
        n2: North coordinate of point 2 in meters
    
    Returns:
        Azimuth angle in degrees, range [0, 360):
        - 0° = North (point 2 is directly North of point 1)
        - 90° = East (point 2 is directly East of point 1)
        - 180° = South (point 2 is directly South of point 1)
        - 270° = West (point 2 is directly West of point 1)
    
    Example:
        >>> # Point 2 is 100m East and 50m North of point 1
        >>> az = calculate_azimuth(0, 0, 100, 50)
        >>> print(f"Azimuth: {az:.1f}°")  # ~63.4° (northeast)
        
        >>> # Point 2 is directly South
        >>> az = calculate_azimuth(0, 0, 0, -100)
        >>> print(f"Azimuth: {az:.1f}°")  # 180.0°
    """
    # Calculate delta E and delta N
    de = e2 - e1
    dn = n2 - n1
    
    # Handle the case where both deltas are zero (same point)
    if de == 0 and dn == 0:
        return 0.0
    
    # Calculate azimuth using arctan2
    # arctan2(y, x) returns angle from x-axis, we want angle from North (y-axis)
    # So we use arctan2(de, dn) which gives angle East of North
    azimuth_rad = np.arctan2(de, dn)
    
    # Convert to degrees
    azimuth_deg = np.degrees(azimuth_rad)
    
    # Normalize to [0, 360)
    if azimuth_deg < 0:
        azimuth_deg += 360.0
    
    return float(azimuth_deg)


def calculate_azimuth_vectorized(
    e1: np.ndarray, 
    n1: np.ndarray, 
    e2: np.ndarray, 
    n2: np.ndarray
) -> np.ndarray:
    """Vectorized azimuth calculation for multiple point pairs.
    
    Args:
        e1: Array of East coordinates for point 1
        n1: Array of North coordinates for point 1
        e2: Array of East coordinates for point 2
        n2: Array of North coordinates for point 2
    
    Returns:
        Array of azimuth angles in degrees [0, 360)
    """
    e1 = np.asarray(e1, dtype=np.float64)
    n1 = np.asarray(n1, dtype=np.float64)
    e2 = np.asarray(e2, dtype=np.float64)
    n2 = np.asarray(n2, dtype=np.float64)
    
    de = e2 - e1
    dn = n2 - n1
    
    azimuth_rad = np.arctan2(de, dn)
    azimuth_deg = np.degrees(azimuth_rad)
    
    # Normalize to [0, 360)
    azimuth_deg = np.where(azimuth_deg < 0, azimuth_deg + 360.0, azimuth_deg)
    
    # Handle case where both deltas are zero
    zero_mask = (de == 0) & (dn == 0)
    azimuth_deg = np.where(zero_mask, 0.0, azimuth_deg)
    
    return azimuth_deg


def calculate_elevation_angle(horizontal_distance: float, height_difference: float) -> float:
    """Calculate elevation angle in degrees.
    
    The elevation angle is measured from the horizontal plane upward.
    
    Args:
        horizontal_distance: Horizontal distance in meters (sqrt(e² + n²))
        height_difference: Height difference in meters (u2 - u1, positive = up)
    
    Returns:
        Elevation angle in degrees:
        - 0° = at horizon level
        - 90° = directly overhead (zenith)
        - Negative values = below horizon
    
    Example:
        >>> # Building 100m away horizontally, 30m taller
        >>> elev = calculate_elevation_angle(100.0, 30.0)
        >>> print(f"Elevation: {elev:.1f}°")  # ~16.7°
        
        >>> # Same height
        >>> elev = calculate_elevation_angle(100.0, 0.0)
        >>> print(f"Elevation: {elev:.1f}°")  # 0.0°
    """
    if horizontal_distance <= 0:
        # If directly overhead or same point
        if height_difference > 0:
            return 90.0
        elif height_difference < 0:
            return -90.0
        else:
            return 0.0
    
    elevation_rad = np.arctan2(height_difference, horizontal_distance)
    return float(np.degrees(elevation_rad))


def calculate_elevation_from_enu(
    e1: float, n1: float, u1: float,
    e2: float, n2: float, u2: float
) -> float:
    """Calculate elevation angle between two points in ENU coordinates.
    
    Args:
        e1, n1, u1: ENU coordinates of point 1 (observer)
        e2, n2, u2: ENU coordinates of point 2 (target)
    
    Returns:
        Elevation angle in degrees from point 1 to point 2
    """
    de = e2 - e1
    dn = n2 - n1
    du = u2 - u1
    
    horizontal_dist = np.sqrt(de ** 2 + dn ** 2)
    
    return calculate_elevation_angle(horizontal_dist, du)


def azimuth_to_sector(azimuth_degrees: float, sector_size: float = 2.0) -> int:
    """Convert azimuth angle to sector index.
    
    Used for discretizing the 360° azimuth range into sectors for
    caching and lookup purposes.
    
    Args:
        azimuth_degrees: Azimuth angle in degrees [0, 360)
        sector_size: Size of each sector in degrees (default 2.0)
    
    Returns:
        Sector index (0 to num_sectors - 1)
    
    Example:
        >>> # With 2° sectors (180 total sectors)
        >>> azimuth_to_sector(0.0)     # 0 (North sector)
        >>> azimuth_to_sector(90.0)    # 45 (East sector)
        >>> azimuth_to_sector(180.0)   # 90 (South sector)
        >>> azimuth_to_sector(1.9)     # 0 (still North sector)
        >>> azimuth_to_sector(2.0)     # 1 (next sector)
        
        >>> # With 5° sectors (72 total sectors)
        >>> azimuth_to_sector(90.0, 5.0)  # 18
    """
    # Normalize azimuth to [0, 360)
    azimuth = azimuth_degrees % 360.0
    
    # Calculate sector index
    sector_index = int(azimuth // sector_size)
    
    # Ensure we don't exceed the maximum sector
    num_sectors = int(360.0 / sector_size)
    if sector_index >= num_sectors:
        sector_index = num_sectors - 1
    
    return sector_index


def sector_to_azimuth_range(sector_index: int, sector_size: float = 2.0) -> Tuple[float, float]:
    """Convert sector index back to azimuth range.
    
    Args:
        sector_index: Sector index (0 to num_sectors - 1)
        sector_size: Size of each sector in degrees
    
    Returns:
        Tuple of (min_azimuth, max_azimuth) in degrees
    
    Example:
        >>> sector_to_azimuth_range(0, 2.0)   # (0.0, 2.0)
        >>> sector_to_azimuth_range(45, 2.0)  # (90.0, 92.0)
    """
    min_azimuth = sector_index * sector_size
    max_azimuth = min_azimuth + sector_size
    return (min_azimuth, max_azimuth)


def calculate_3d_distance(
    e1: float, n1: float, u1: float,
    e2: float, n2: float, u2: float
) -> float:
    """Calculate 3D Euclidean distance between two points in ENU.
    
    Args:
        e1, n1, u1: ENU coordinates of point 1
        e2, n2, u2: ENU coordinates of point 2
    
    Returns:
        3D distance in meters
    """
    de = e2 - e1
    dn = n2 - n1
    du = u2 - u1
    
    return float(np.sqrt(de ** 2 + dn ** 2 + du ** 2))


def calculate_horizontal_distance(e1: float, n1: float, e2: float, n2: float) -> float:
    """Calculate horizontal (ground) distance between two points.
    
    Args:
        e1, n1: ENU horizontal coordinates of point 1
        e2, n2: ENU horizontal coordinates of point 2
    
    Returns:
        Horizontal distance in meters
    """
    de = e2 - e1
    dn = n2 - n1
    
    return float(np.sqrt(de ** 2 + dn ** 2))


def get_cardinal_direction(azimuth_degrees: float) -> str:
    """Convert azimuth to cardinal/intercardinal direction.
    
    Args:
        azimuth_degrees: Azimuth angle in degrees [0, 360)
    
    Returns:
        Cardinal direction string (N, NE, E, SE, S, SW, W, NW)
    
    Example:
        >>> get_cardinal_direction(0)     # 'N'
        >>> get_cardinal_direction(45)    # 'NE'
        >>> get_cardinal_direction(90)    # 'E'
        >>> get_cardinal_direction(225)   # 'SW'
    """
    # Normalize to [0, 360)
    azimuth = azimuth_degrees % 360.0
    
    # Define direction boundaries (centered on each direction)
    # N: 337.5 - 22.5, NE: 22.5 - 67.5, etc.
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'N']
    boundaries = [0, 22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5, 360]
    
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= azimuth < boundaries[i + 1]:
            return directions[i]
    
    return 'N'  # Default for 360


def calculate_line_of_sight_vector(
    e1: float, n1: float, u1: float,
    e2: float, n2: float, u2: float
) -> Tuple[float, float, float]:
    """Calculate normalized line-of-sight vector from point 1 to point 2.
    
    Args:
        e1, n1, u1: ENU coordinates of observer
        e2, n2, u2: ENU coordinates of target
    
    Returns:
        Tuple of (east_component, north_component, up_component) as unit vector
    """
    de = e2 - e1
    dn = n2 - n1
    du = u2 - u1
    
    dist = np.sqrt(de ** 2 + dn ** 2 + du ** 2)
    
    if dist == 0:
        return (0.0, 0.0, 1.0)  # Default to up if same point
    
    return (float(de / dist), float(dn / dist), float(du / dist))
