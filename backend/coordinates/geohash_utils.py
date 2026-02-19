"""Geohash utilities for spatial caching. BSD License.

This module provides utilities for encoding/decoding geohashes and
finding geohashes within a radius for spatial indexing and caching.

Geohash Properties:
- Hierarchical spatial indexing system
- Base32 encoding (characters: 0123456789bcdefghjkmnpqrstuvwxyz)
- Each additional character increases precision
- Geohash-6: ~1.2km x 0.6km cells (suitable for city-scale caching)
- Geohash-7: ~150m x 150m cells (suitable for neighborhood caching)
- Geohash-8: ~20m x 20m cells (suitable for building-scale caching)

Precision Table:
- 1 char: ~5,000km x 5,000km
- 2 char: ~1,250km x 625km
- 3 char: ~156km x 156km
- 4 char: ~39km x 19.5km
- 5 char: ~4.9km x 4.9km
- 6 char: ~1.2km x 0.6km (recommended for LinkSpot)
- 7 char: ~150m x 150m
- 8 char: ~20m x 20m
- 9 char: ~2.4m x 2.4m
"""

import pygeohash as pgh
from typing import Tuple, Dict, List, Set, Optional
import math

# Geohash character set (base32)
GEOHASH_CHARS = '0123456789bcdefghjkmnpqrstuvwxyz'
BASE32_CHARS = GEOHASH_CHARS

# Approximate cell dimensions at each precision level (latitude ~45°)
# Format: (width_km, height_km)
GEOHASH_DIMENSIONS = {
    1: (5000.0, 5000.0),
    2: (1250.0, 625.0),
    3: (156.0, 156.0),
    4: (39.0, 19.5),
    5: (4.9, 4.9),
    6: (1.2, 0.6),
    7: (0.15, 0.15),
    8: (0.02, 0.02),
    9: (0.0024, 0.0024),
}


def encode_geohash(lat: float, lon: float, precision: int = 6) -> str:
    """Encode latitude/longitude to geohash string.
    
    Args:
        lat: Latitude in degrees (-90 to 90)
        lon: Longitude in degrees (-180 to 180)
        precision: Number of characters in geohash (1-12, default 6)
    
    Returns:
        Geohash string of specified precision
    
    Example:
        >>> encode_geohash(47.6062, -122.3321, 6)
        'c23n8j'
        
        >>> encode_geohash(40.7128, -74.0060, 7)  # NYC
        'dr5r9x1'
    """
    return pgh.encode(lat, lon, precision)


def decode_geohash(geohash: str) -> Tuple[float, float, float, float]:
    """Decode geohash to latitude/longitude with error bounds.
    
    Args:
        geohash: Geohash string to decode
    
    Returns:
        Tuple of (lat, lon, lat_error, lon_error) where:
        - lat: Center latitude in degrees
        - lon: Center longitude in degrees
        - lat_error: Latitude uncertainty (half cell height) in degrees
        - lon_error: Longitude uncertainty (half cell width) in degrees
    
    Example:
        >>> decode_geohash('c23n8j')
        (47.6062, -122.3321, 0.0027, 0.0055)  # approximate
    """
    return pgh.decode_exactly(geohash)


def decode_geohash_center(geohash: str) -> Tuple[float, float]:
    """Decode geohash to center latitude/longitude only.
    
    Args:
        geohash: Geohash string to decode
    
    Returns:
        Tuple of (lat, lon) for the cell center
    """
    lat, lon, _, _ = pgh.decode_exactly(geohash)
    return (lat, lon)


def get_geohash_bounds(geohash: str) -> Tuple[float, float, float, float]:
    """Get the bounding box of a geohash cell.
    
    Args:
        geohash: Geohash string
    
    Returns:
        Tuple of (min_lat, min_lon, max_lat, max_lon)
    """
    lat, lon, lat_err, lon_err = pgh.decode_exactly(geohash)
    return (
        lat - lat_err,  # min_lat
        lon - lon_err,  # min_lon
        lat + lat_err,  # max_lat
        lon + lon_err   # max_lon
    )


def get_geohash_dimensions(precision: int) -> Tuple[float, float]:
    """Get approximate dimensions of geohash cells at given precision.
    
    Args:
        precision: Geohash precision level (1-9)
    
    Returns:
        Tuple of (width_km, height_km) at ~45° latitude
    """
    if precision in GEOHASH_DIMENSIONS:
        return GEOHASH_DIMENSIONS[precision]
    
    # Estimate for higher precisions
    # Each level roughly halves the dimensions
    base_prec = min(precision, 9)
    width, height = GEOHASH_DIMENSIONS[base_prec]
    scale = 0.5 ** (precision - base_prec)
    
    return (width * scale, height * scale)


def get_geohashes_in_radius(
    lat: float, 
    lon: float, 
    radius_m: float, 
    precision: int = 6
) -> List[str]:
    """Get all geohashes within a radius of a point.
    
    This is useful for spatial queries where you need to find all
    cached data within a certain distance of a location.
    
    Args:
        lat: Center latitude in degrees
        lon: Center longitude in degrees
        radius_m: Radius in meters
        precision: Geohash precision (default 6)
    
    Returns:
        List of unique geohash strings within the radius
    
    Example:
        >>> # Get all geohashes within 2km of Seattle center
        >>> geohashes = get_geohashes_in_radius(47.6062, -122.3321, 2000, 6)
        >>> print(len(geohashes))  # Typically 9-25 geohashes
    """
    # Get center geohash
    center_geohash = pgh.encode(lat, lon, precision)
    
    # Get all neighboring geohashes
    neighbors = get_neighbors(center_geohash)
    
    # Include center in the set
    all_geohashes = set(neighbors)
    all_geohashes.add(center_geohash)
    
    # For larger radii, we need to expand further
    # Estimate how many cell layers we need
    cell_width_km, cell_height_km = get_geohash_dimensions(precision)
    cell_size_km = max(cell_width_km, cell_height_km)
    radius_km = radius_m / 1000.0
    
    # Number of layers needed (with some margin)
    layers_needed = int(radius_km / cell_size_km) + 1
    
    if layers_needed > 1:
        # Expand by getting neighbors of neighbors
        current_layer = set(all_geohashes)
        for _ in range(layers_needed - 1):
            next_layer = set()
            for gh in current_layer:
                next_layer.update(get_neighbors(gh))
            all_geohashes.update(next_layer)
            current_layer = next_layer
    
    # Filter to only include geohashes whose centers are within radius
    result = []
    for gh in all_geohashes:
        gh_lat, gh_lon = decode_geohash_center(gh)
        dist = haversine_distance(lat, lon, gh_lat, gh_lon)
        if dist <= radius_m + (cell_size_km * 500):  # Add half cell size margin
            result.append(gh)
    
    return sorted(result)


def get_neighbors(geohash: str) -> List[str]:
    """Get all 8 neighboring geohashes.
    
    Args:
        geohash: Base geohash string
    
    Returns:
        List of 8 neighboring geohashes in order:
        [N, NE, E, SE, S, SW, W, NW]
    """
    try:
        return pgh.neighbors(geohash)
    except Exception:
        # Fallback implementation if pygeohash.neighbors fails
        return _get_neighbors_manual(geohash)


def _get_neighbors_manual(geohash: str) -> List[str]:
    """Manual implementation of neighbor calculation.
    
    Used as fallback if pygeohash.neighbors is not available.
    """
    lat, lon, lat_err, lon_err = pgh.decode_exactly(geohash)
    precision = len(geohash)
    
    neighbors = []
    
    # N
    neighbors.append(pgh.encode(lat + 2 * lat_err, lon, precision))
    # NE
    neighbors.append(pgh.encode(lat + 2 * lat_err, lon + 2 * lon_err, precision))
    # E
    neighbors.append(pgh.encode(lat, lon + 2 * lon_err, precision))
    # SE
    neighbors.append(pgh.encode(lat - 2 * lat_err, lon + 2 * lon_err, precision))
    # S
    neighbors.append(pgh.encode(lat - 2 * lat_err, lon, precision))
    # SW
    neighbors.append(pgh.encode(lat - 2 * lat_err, lon - 2 * lon_err, precision))
    # W
    neighbors.append(pgh.encode(lat, lon - 2 * lon_err, precision))
    # NW
    neighbors.append(pgh.encode(lat + 2 * lat_err, lon - 2 * lon_err, precision))
    
    return neighbors


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point coordinates in degrees
        lat2, lon2: Second point coordinates in degrees
    
    Returns:
        Distance in meters
    """
    R = 6371000  # Earth's radius in meters (mean)
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def get_geohash_precision_for_radius(radius_m: float) -> int:
    """Recommend geohash precision for a given search radius.
    
    Args:
        radius_m: Search radius in meters
    
    Returns:
        Recommended geohash precision level
    
    Example:
        >>> get_geohash_precision_for_radius(100)   # 7 (150m cells)
        >>> get_geohash_precision_for_radius(1000)  # 6 (1.2km cells)
        >>> get_geohash_precision_for_radius(10000) # 5 (5km cells)
    """
    if radius_m < 50:
        return 8
    elif radius_m < 200:
        return 7
    elif radius_m < 1000:
        return 6
    elif radius_m < 5000:
        return 5
    elif radius_m < 20000:
        return 4
    elif radius_m < 100000:
        return 3
    else:
        return 2


def expand_geohash_prefix(geohash_prefix: str) -> List[str]:
    """Expand a geohash prefix to all possible full geohashes.
    
    Useful for wildcard searches (e.g., 'c23n8*' -> all 32 7-char geohashes).
    
    Args:
        geohash_prefix: Partial geohash string
    
    Returns:
        List of all possible full geohashes with that prefix
    """
    current = [geohash_prefix]
    
    # Expand to precision 6 (default) or 7 for finer granularity
    target_precision = 6
    
    while len(current[0]) < target_precision:
        next_level = []
        for gh in current:
            for char in GEOHASH_CHARS:
                next_level.append(gh + char)
        current = next_level
    
    return current


def are_geohashes_adjacent(geohash1: str, geohash2: str) -> bool:
    """Check if two geohashes are adjacent (share a border).
    
    Args:
        geohash1: First geohash string
        geohash2: Second geohash string
    
    Returns:
        True if geohashes are adjacent, False otherwise
    """
    if len(geohash1) != len(geohash2):
        return False
    
    return geohash2 in get_neighbors(geohash1)


def get_parent_geohash(geohash: str) -> Optional[str]:
    """Get the parent (one precision level less) of a geohash.
    
    Args:
        geohash: Geohash string
    
    Returns:
        Parent geohash or None if already at precision 1
    """
    if len(geohash) <= 1:
        return None
    return geohash[:-1]


def get_common_prefix(
    geohashes: List[str] | str,
    *more_geohashes: str,
) -> str:
    """Find the common prefix of multiple geohashes.

    Accepts either a list of geohashes or positional geohash arguments.
    """
    if isinstance(geohashes, str):
        values = [geohashes, *more_geohashes]
    else:
        values = list(geohashes)
        if more_geohashes:
            values.extend(more_geohashes)

    if not values:
        return ''
    
    prefix = []
    for chars in zip(*values):
        if len(set(chars)) == 1:
            prefix.append(chars[0])
        else:
            break
    
    return ''.join(prefix)


def geohash_to_bbox(geohash: str) -> Tuple[float, float, float, float]:
    """Backward-compatible alias for get_geohash_bounds()."""
    return get_geohash_bounds(geohash)


def bbox_to_geohashes(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    precision: int = 6,
) -> List[str]:
    """Generate geohashes that cover a bounding box."""
    if min_lat > max_lat or min_lon > max_lon:
        raise ValueError("Invalid bbox: min values must be <= max values")

    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    sample = encode_geohash(center_lat, center_lon, precision)
    s_min_lat, s_min_lon, s_max_lat, s_max_lon = get_geohash_bounds(sample)
    lat_step = max((s_max_lat - s_min_lat) / 2.0, 1e-6)
    lon_step = max((s_max_lon - s_min_lon) / 2.0, 1e-6)

    geohashes: Set[str] = set()
    lat = min_lat
    while lat <= max_lat + lat_step:
        lon = min_lon
        while lon <= max_lon + lon_step:
            geohashes.add(encode_geohash(lat, lon, precision))
            lon += lon_step
        lat += lat_step

    return sorted(geohashes)


def get_precision_for_radius(radius_m: float) -> int:
    """Backward-compatible alias for get_geohash_precision_for_radius()."""
    return get_geohash_precision_for_radius(radius_m)


def are_neighbors(geohash1: str, geohash2: str) -> bool:
    """Backward-compatible alias for are_geohashes_adjacent()."""
    return are_geohashes_adjacent(geohash1, geohash2)


def get_parent(geohash: str) -> Optional[str]:
    """Backward-compatible alias for get_parent_geohash()."""
    return get_parent_geohash(geohash)


def get_children(geohash: str) -> List[str]:
    """Return all 32 one-level child geohashes."""
    return [f"{geohash}{char}" for char in GEOHASH_CHARS]


def get_geohash_area(geohash: str) -> float:
    """Approximate geohash cell area in square meters."""
    min_lat, min_lon, max_lat, max_lon = get_geohash_bounds(geohash)
    width_m = haversine_distance(min_lat, min_lon, min_lat, max_lon)
    height_m = haversine_distance(min_lat, min_lon, max_lat, min_lon)
    return width_m * height_m


def encode_geohash_vectorized(
    lats: List[float],
    lons: List[float],
    precision: int = 6,
) -> List[str]:
    """Vectorized geohash encoder for array-like inputs."""
    return [encode_geohash(float(lat), float(lon), precision) for lat, lon in zip(lats, lons)]
