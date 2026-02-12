#!/usr/bin/env python3
"""
Comprehensive Unit Tests for LinkSpot Coordinate System Utilities

This test suite validates:
- ENU coordinate transformations (WGS84 ↔ ENU)
- Azimuth and elevation calculations
- Distance calculations (Haversine, Vincenty, Euclidean)
- Geohash encoding/decoding and spatial operations
- Edge cases (poles, equator, antimeridian)
- Numerical stability

Test Coverage:
==============
- Scalar and vectorized operations
- Round-trip conversions
- Known reference values
- Boundary conditions
- Error propagation

Run with: python -m pytest test_coordinates.py -v
"""

import math
import unittest
from typing import Tuple

import numpy as np

# Import the modules under test
from enu_transforms import (
    wgs84_to_ecef,
    ecef_to_wgs84,
    wgs84_to_enu,
    enu_to_wgs84,
    wgs84_to_enu_vectorized,
    enu_to_wgs84_vectorized,
    _compute_rotation_matrix,
    get_enu_accuracy_estimate,
    WGS84_A,
    WGS84_B,
)

from azimuth_elevation import (
    calculate_azimuth,
    calculate_elevation_angle,
    calculate_azimuth_elevation_enu,
    calculate_satellite_azimuth_elevation,
    azimuth_to_sector,
    sector_to_azimuth_range,
    calculate_slant_range,
    is_above_horizon,
    calculate_look_angles_to_multiple_targets,
    get_cardinal_direction,
)

from distance import (
    haversine_distance,
    haversine_distance_vectorized,
    vincenty_distance,
    euclidean_distance_enu,
    euclidean_distance_enu_vectorized,
    horizontal_distance_enu,
    horizontal_distance_enu_vectorized,
    distance_along_parallel,
    distance_along_meridian,
    is_within_distance,
    EARTH_MEAN_RADIUS,
)

from geohash_utils import (
    encode_geohash,
    decode_geohash,
    get_neighbors,
    geohash_to_bbox,
    bbox_to_geohashes,
    get_geohashes_in_radius,
    get_common_prefix,
    get_precision_for_radius,
    are_neighbors,
    get_parent,
    get_children,
    get_geohash_area,
    BASE32_CHARS,
)


# =============================================================================
# Test Constants and Reference Data
# =============================================================================

# Known reference points for validation
REFERENCE_POINTS = {
    'null_island': (0.0, 0.0, 0.0),  # Equator/Prime Meridian
    'n_pole': (90.0, 0.0, 0.0),  # North Pole
    's_pole': (-90.0, 0.0, 0.0),  # South Pole
    'nyc': (40.7128, -74.0060, 10.0),  # New York City
    'london': (51.5074, -0.1278, 11.0),  # London
    'tokyo': (35.6762, 139.6503, 40.0),  # Tokyo
    'sydney': (-33.8688, 151.2093, 3.0),  # Sydney
    'antimeridian_e': (0.0, 179.999, 0.0),  # Near antimeridian (East)
    'antimeridian_w': (0.0, -179.999, 0.0),  # Near antimeridian (West)
}

# Tolerance values for floating-point comparisons
TOLERANCE_MM = 0.001  # 1 mm
TOLERANCE_CM = 0.01   # 1 cm
TOLERANCE_M = 0.1     # 10 cm
TOLERANCE_DEG = 1e-8  # ~1 mm at equator


# =============================================================================
# ENU Transformation Tests
# =============================================================================

class TestENUTransforms(unittest.TestCase):
    """Test ENU coordinate transformations."""
    
    def test_wgs84_to_ecef_known_values(self):
        """Test WGS84 to ECEF conversion with known reference values."""
        # Null Island (0, 0, 0) should give (a, 0, 0)
        x, y, z = wgs84_to_ecef(0.0, 0.0, 0.0)
        self.assertAlmostEqual(x, WGS84_A, delta=TOLERANCE_M)
        self.assertAlmostEqual(y, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(z, 0.0, delta=TOLERANCE_MM)
        
        # North Pole
        x, y, z = wgs84_to_ecef(90.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(y, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(z, WGS84_B, delta=TOLERANCE_M)
        
        # South Pole
        x, y, z = wgs84_to_ecef(-90.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(y, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(z, -WGS84_B, delta=TOLERANCE_M)
    
    def test_ecef_to_wgs84_roundtrip(self):
        """Test ECEF to WGS84 round-trip conversion."""
        test_points = [
            (0.0, 0.0, 0.0),
            (40.7128, -74.0060, 10.0),
            (-33.8688, 151.2093, 3.0),
            (89.9, 45.0, 100.0),  # Near pole
        ]
        
        for lat, lon, elev in test_points:
            x, y, z = wgs84_to_ecef(lat, lon, elev)
            lat_back, lon_back, elev_back = ecef_to_wgs84(x, y, z)
            
            self.assertAlmostEqual(lat, lat_back, delta=TOLERANCE_DEG)
            self.assertAlmostEqual(lon, lon_back, delta=TOLERANCE_DEG)
            self.assertAlmostEqual(elev, elev_back, delta=TOLERANCE_MM)
    
    def test_wgs84_to_enu_origin(self):
        """Test that reference point maps to ENU origin."""
        lat, lon, elev = 40.7128, -74.0060, 10.0
        e, n, u = wgs84_to_enu(lat, lon, elev, lat, lon, elev)
        
        self.assertAlmostEqual(e, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(n, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(u, 0.0, delta=TOLERANCE_MM)
    
    def test_wgs84_to_enu_roundtrip(self):
        """Test WGS84 → ENU → WGS84 round-trip conversion."""
        test_cases = [
            # (point_lat, point_lon, point_elev, ref_lat, ref_lon, ref_elev)
            (40.72, -74.01, 15.0, 40.71, -74.00, 10.0),  # NYC area
            (51.51, -0.13, 20.0, 51.50, -0.12, 10.0),   # London area
            (35.68, 139.65, 50.0, 35.67, 139.64, 40.0), # Tokyo area
            (0.01, 0.01, 10.0, 0.0, 0.0, 0.0),          # Near equator
        ]
        
        for plat, plon, pelev, rlat, rlon, relev in test_cases:
            # Forward conversion
            e, n, u = wgs84_to_enu(plat, plon, pelev, rlat, rlon, relev)
            
            # Reverse conversion
            lat_back, lon_back, elev_back = enu_to_wgs84(e, n, u, rlat, rlon, relev)
            
            # Check round-trip accuracy
            self.assertAlmostEqual(plat, lat_back, delta=TOLERANCE_DEG)
            self.assertAlmostEqual(plon, lon_back, delta=TOLERANCE_DEG)
            self.assertAlmostEqual(pelev, elev_back, delta=TOLERANCE_MM)
    
    def test_enu_directions(self):
        """Test that ENU axes point in correct directions."""
        ref_lat, ref_lon, ref_elev = 40.0, -74.0, 0.0
        
        # Point due North (same longitude, higher latitude)
        e, n, u = wgs84_to_enu(40.001, -74.0, 0.0, ref_lat, ref_lon, ref_elev)
        self.assertGreater(n, 0)  # North should be positive
        self.assertAlmostEqual(e, 0.0, delta=1.0)  # East ~ 0
        
        # Point due South (same longitude, lower latitude)
        e, n, u = wgs84_to_enu(39.999, -74.0, 0.0, ref_lat, ref_lon, ref_elev)
        self.assertLess(n, 0)  # North should be negative
        
        # Point due East (same latitude, higher longitude)
        e, n, u = wgs84_to_enu(40.0, -73.999, 0.0, ref_lat, ref_lon, ref_elev)
        self.assertGreater(e, 0)  # East should be positive
        self.assertAlmostEqual(n, 0.0, delta=1.0)  # North ~ 0
        
        # Point due West (same latitude, lower longitude)
        e, n, u = wgs84_to_enu(40.0, -74.001, 0.0, ref_lat, ref_lon, ref_elev)
        self.assertLess(e, 0)  # East should be negative
        
        # Point higher up
        e, n, u = wgs84_to_enu(40.0, -74.0, 100.0, ref_lat, ref_lon, ref_elev)
        self.assertGreater(u, 0)  # Up should be positive
        self.assertAlmostEqual(e, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(n, 0.0, delta=TOLERANCE_MM)
    
    def test_vectorized_operations(self):
        """Test that vectorized operations match scalar operations."""
        # Create test arrays
        lats = np.array([40.71, 40.72, 40.73, 40.74])
        lons = np.array([-74.01, -74.02, -74.03, -74.04])
        elevs = np.array([10.0, 15.0, 20.0, 25.0])
        ref_lat, ref_lon, ref_elev = 40.70, -74.00, 0.0
        
        # Vectorized conversion
        e_vec, n_vec, u_vec = wgs84_to_enu_vectorized(
            lats, lons, elevs, ref_lat, ref_lon, ref_elev
        )
        
        # Compare with scalar conversions
        for i in range(len(lats)):
            e_scal, n_scal, u_scal = wgs84_to_enu(
                lats[i], lons[i], elevs[i], ref_lat, ref_lon, ref_elev
            )
            self.assertAlmostEqual(e_vec[i], e_scal, delta=TOLERANCE_MM)
            self.assertAlmostEqual(n_vec[i], n_scal, delta=TOLERANCE_MM)
            self.assertAlmostEqual(u_vec[i], u_scal, delta=TOLERANCE_MM)
    
    def test_vectorized_roundtrip(self):
        """Test vectorized round-trip conversion."""
        lats = np.array([40.71, 40.72, 40.73])
        lons = np.array([-74.01, -74.02, -74.03])
        elevs = np.array([10.0, 15.0, 20.0])
        ref_lat, ref_lon, ref_elev = 40.70, -74.00, 0.0
        
        # Forward
        e, n, u = wgs84_to_enu_vectorized(lats, lons, elevs, ref_lat, ref_lon, ref_elev)
        
        # Reverse
        lats_back, lons_back, elevs_back = enu_to_wgs84_vectorized(
            e, n, u, ref_lat, ref_lon, ref_elev
        )
        
        # Check
        np.testing.assert_array_almost_equal(lats, lats_back, decimal=8)
        np.testing.assert_array_almost_equal(lons, lons_back, decimal=8)
        np.testing.assert_array_almost_equal(elevs, elevs_back, decimal=3)
    
    def test_pole_edge_cases(self):
        """Test ENU conversion near poles."""
        # Near North Pole
        ref_lat, ref_lon, ref_elev = 89.9, 0.0, 0.0
        point_lat, point_lon, point_elev = 89.95, 90.0, 0.0
        
        e, n, u = wgs84_to_enu(point_lat, point_lon, point_elev,
                               ref_lat, ref_lon, ref_elev)
        
        # Should produce valid coordinates
        self.assertTrue(math.isfinite(e))
        self.assertTrue(math.isfinite(n))
        self.assertTrue(math.isfinite(u))
        
        # Round-trip should work
        lat_back, lon_back, elev_back = enu_to_wgs84(e, n, u, ref_lat, ref_lon, ref_elev)
        self.assertAlmostEqual(point_lat, lat_back, delta=1e-4)
        self.assertAlmostEqual(point_lon, lon_back, delta=1e-4)
    
    def test_antimeridian_edge_cases(self):
        """Test ENU conversion across the antimeridian (±180° longitude)."""
        # Reference just west of antimeridian
        ref_lat, ref_lon, ref_elev = 0.0, 179.9, 0.0
        
        # Point just east of antimeridian (should be close)
        point_lat, point_lon, point_elev = 0.0, -179.9, 0.0
        
        e, n, u = wgs84_to_enu(point_lat, point_lon, point_elev,
                               ref_lat, ref_lon, ref_elev)
        
        # These points are only 0.2° apart, so ENU distance should be small
        distance = math.sqrt(e**2 + n**2)
        self.assertLess(distance, 50000)  # Less than 50 km
    
    def test_invalid_inputs(self):
        """Test that invalid inputs raise appropriate errors."""
        # Invalid latitude
        with self.assertRaises(ValueError):
            wgs84_to_enu(91.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        
        with self.assertRaises(ValueError):
            wgs84_to_enu(0.0, 0.0, 0.0, -91.0, 0.0, 0.0)
        
        # Invalid longitude
        with self.assertRaises(ValueError):
            wgs84_to_enu(0.0, 181.0, 0.0, 0.0, 0.0, 0.0)
        
        with self.assertRaises(ValueError):
            enu_to_wgs84(0.0, 0.0, 0.0, 0.0, 181.0, 0.0)


# =============================================================================
# Azimuth and Elevation Tests
# =============================================================================

class TestAzimuthElevation(unittest.TestCase):
    """Test azimuth and elevation calculations."""
    
    def test_azimuth_cardinal_directions(self):
        """Test azimuth calculation for cardinal directions."""
        # From origin to various directions
        test_cases = [
            ((0, 0), (0, 100), 0.0),      # North
            ((0, 0), (100, 0), 90.0),     # East
            ((0, 0), (0, -100), 180.0),   # South
            ((0, 0), (-100, 0), 270.0),   # West
            ((0, 0), (100, 100), 45.0),   # Northeast
            ((0, 0), (100, -100), 135.0), # Southeast
            ((0, 0), (-100, -100), 225.0),# Southwest
            ((0, 0), (-100, 100), 315.0), # Northwest
        ]
        
        for (e1, n1), (e2, n2), expected_az in test_cases:
            az = calculate_azimuth(e1, n1, e2, n2)
            self.assertAlmostEqual(az, expected_az, delta=0.01,
                msg=f"Failed for ({e1},{n1}) to ({e2},{n2})")
    
    def test_azimuth_same_point(self):
        """Test azimuth when observer and target are the same."""
        az = calculate_azimuth(100, 200, 100, 200)
        self.assertEqual(az, 0.0)  # Should return 0 by convention
    
    def test_elevation_angle(self):
        """Test elevation angle calculation."""
        test_cases = [
            (1000, 0, 0.0),       # Level
            (1000, 100, 5.71),    # Slight upward angle
            (1000, -100, -5.71),  # Slight downward angle
            (1000, 1000, 45.0),   # 45 degrees up
            (0, 100, 90.0),       # Directly overhead
            (0, -100, -90.0),     # Directly below
        ]
        
        for horiz_dist, height_diff, expected_el in test_cases:
            el = calculate_elevation_angle(horiz_dist, height_diff)
            self.assertAlmostEqual(el, expected_el, delta=0.01,
                msg=f"Failed for horiz={horiz_dist}, height={height_diff}")
    
    def test_azimuth_elevation_combined(self):
        """Test combined azimuth and elevation calculation."""
        # Observer at origin, target at known position
        az, el = calculate_azimuth_elevation_enu(0, 0, 0, 1000, 1000, 100)
        
        self.assertAlmostEqual(az, 45.0, delta=0.01)  # Northeast
        # Elevation should be atan(100 / sqrt(1000^2 + 1000^2))
        expected_el = math.degrees(math.atan(100 / math.sqrt(2 * 1000**2)))
        self.assertAlmostEqual(el, expected_el, delta=0.01)
    
    def test_satellite_azimuth_elevation(self):
        """Test satellite visibility calculation."""
        # Observer in NYC, geostationary satellite at equator
        az, el = calculate_satellite_azimuth_elevation(
            40.7128, -74.0060, 10.0,  # NYC
            0.0, -75.0, 35786000.0     # Geostationary satellite
        )
        
        # Satellite should be roughly South with low elevation
        self.assertGreater(az, 90)
        self.assertLess(az, 270)
        self.assertGreater(el, -10)  # Should be above horizon
    
    def test_azimuth_to_sector(self):
        """Test azimuth to sector conversion."""
        # 2° sectors (default)
        self.assertEqual(azimuth_to_sector(0), 0)      # North
        self.assertEqual(azimuth_to_sector(90), 45)    # East
        self.assertEqual(azimuth_to_sector(180), 90)   # South
        self.assertEqual(azimuth_to_sector(270), 135)  # West
        self.assertEqual(azimuth_to_sector(359), 179)  # Just before North
        
        # 5° sectors
        self.assertEqual(azimuth_to_sector(0, 5), 0)
        self.assertEqual(azimuth_to_sector(90, 5), 18)
        self.assertEqual(azimuth_to_sector(180, 5), 36)
    
    def test_sector_to_azimuth_range(self):
        """Test sector to azimuth range conversion."""
        start, end = sector_to_azimuth_range(0)
        self.assertEqual(start, 0.0)
        self.assertEqual(end, 2.0)
        
        start, end = sector_to_azimuth_range(45)
        self.assertEqual(start, 90.0)
        self.assertEqual(end, 92.0)
    
    def test_slant_range(self):
        """Test slant range calculation."""
        # 3-4-5 triangle in horizontal plane
        sr = calculate_slant_range(0, 0, 0, 3, 4, 0)
        self.assertAlmostEqual(sr, 5.0, delta=0.001)
        
        # 3D diagonal
        sr = calculate_slant_range(0, 0, 0, 1, 1, 1)
        self.assertAlmostEqual(sr, math.sqrt(3), delta=0.001)
    
    def test_is_above_horizon(self):
        """Test horizon visibility check."""
        # Target above observer
        self.assertTrue(is_above_horizon(0, 0, 0, 1000, 0, 100))
        
        # Target at same height
        self.assertTrue(is_above_horizon(0, 0, 0, 1000, 0, 0))
        
        # Target below observer
        self.assertFalse(is_above_horizon(0, 0, 100, 1000, 0, 0))
        
        # With minimum elevation threshold
        self.assertFalse(is_above_horizon(0, 0, 0, 1000, 0, 10, min_elevation=5.0))
    
    def test_cardinal_direction_names(self):
        """Test cardinal direction name conversion."""
        self.assertEqual(get_cardinal_direction(0), 'N')
        self.assertEqual(get_cardinal_direction(45), 'NE')
        self.assertEqual(get_cardinal_direction(90), 'E')
        self.assertEqual(get_cardinal_direction(135), 'SE')
        self.assertEqual(get_cardinal_direction(180), 'S')
        self.assertEqual(get_cardinal_direction(225), 'SW')
        self.assertEqual(get_cardinal_direction(270), 'W')
        self.assertEqual(get_cardinal_direction(315), 'NW')
        self.assertEqual(get_cardinal_direction(22.5), 'NNE')
    
    def test_vectorized_look_angles(self):
        """Test vectorized look angle calculations."""
        # Multiple targets
        targets_e = np.array([1000, 0, -1000, 0])
        targets_n = np.array([0, 1000, 0, -1000])
        targets_u = np.array([0, 0, 0, 0])
        
        azimuths, elevations, ranges_arr = calculate_look_angles_to_multiple_targets(
            0, 0, 0, targets_e, targets_n, targets_u
        )
        
        # Check cardinal directions
        self.assertAlmostEqual(azimuths[0], 90.0, delta=0.01)   # East
        self.assertAlmostEqual(azimuths[1], 0.0, delta=0.01)    # North
        self.assertAlmostEqual(azimuths[2], 270.0, delta=0.01)  # West
        self.assertAlmostEqual(azimuths[3], 180.0, delta=0.01)  # South


# =============================================================================
# Distance Calculation Tests
# =============================================================================

class TestDistanceCalculations(unittest.TestCase):
    """Test distance calculation methods."""
    
    def test_haversine_known_distances(self):
        """Test Haversine formula with known distances."""
        # Quarter meridian (equator to pole on spherical Earth)
        d = haversine_distance(0, 0, 90, 0)
        expected = EARTH_MEAN_RADIUS * math.pi / 2
        self.assertAlmostEqual(d, expected, delta=100)  # ~100m tolerance
        
        # Distance along equator for 1 degree
        d = haversine_distance(0, 0, 0, 1)
        expected = EARTH_MEAN_RADIUS * math.radians(1)
        self.assertAlmostEqual(d, expected, delta=1)
    
    def test_haversine_vectorized(self):
        """Test vectorized Haversine distance."""
        lats1 = np.array([0.0, 40.0])
        lons1 = np.array([0.0, -74.0])
        lats2 = np.array([0.0, 40.001])
        lons2 = np.array([1.0, -74.0])
        
        distances = haversine_distance_vectorized(lats1, lons1, lats2, lons2)
        
        # Check first distance (along equator)
        expected_0 = EARTH_MEAN_RADIUS * math.radians(1)
        self.assertAlmostEqual(distances[0], expected_0, delta=1)
    
    def test_vincenty_vs_haversine(self):
        """Compare Vincenty and Haversine distances."""
        # For short distances, they should be very close
        d_hav = haversine_distance(40.7128, -74.0060, 40.72, -74.01)
        d_vin = vincenty_distance(40.7128, -74.0060, 40.72, -74.01)
        
        # Should agree within 0.5% for this distance
        self.assertLess(abs(d_hav - d_vin) / d_vin, 0.005)
    
    def test_vincenty_coincident_points(self):
        """Test Vincenty distance for coincident points."""
        d = vincenty_distance(40.7128, -74.0060, 40.7128, -74.0060)
        self.assertEqual(d, 0.0)
    
    def test_euclidean_distance_enu(self):
        """Test 3D Euclidean distance in ENU frame."""
        # Simple cases
        self.assertAlmostEqual(
            euclidean_distance_enu(0, 0, 0, 3, 4, 0), 5.0, delta=0.001
        )
        self.assertAlmostEqual(
            euclidean_distance_enu(0, 0, 0, 1, 1, 1), math.sqrt(3), delta=0.001
        )
        self.assertEqual(euclidean_distance_enu(0, 0, 0, 0, 0, 0), 0.0)
    
    def test_horizontal_distance_enu(self):
        """Test 2D horizontal distance in ENU frame."""
        self.assertAlmostEqual(
            horizontal_distance_enu(0, 0, 3, 4), 5.0, delta=0.001
        )
        self.assertAlmostEqual(
            horizontal_distance_enu(0, 0, 1, 1), math.sqrt(2), delta=0.001
        )
    
    def test_distance_along_parallel(self):
        """Test distance along a parallel."""
        # At equator, 1° longitude ≈ 111.3 km
        d_eq = distance_along_parallel(0, 1)
        self.assertAlmostEqual(d_eq, 111319, delta=1000)
        
        # At 45° latitude, distance should be less
        d_45 = distance_along_parallel(45, 1)
        self.assertLess(d_45, d_eq)
        
        # At poles, distance should be ~0
        d_pole = distance_along_parallel(90, 1)
        self.assertAlmostEqual(d_pole, 0, delta=1)
    
    def test_distance_along_meridian(self):
        """Test distance along a meridian."""
        # 1° latitude ≈ 111 km
        d = distance_along_meridian(1)
        self.assertAlmostEqual(d, 111000, delta=2000)
    
    def test_is_within_distance(self):
        """Test distance threshold check."""
        # NYC to Philadelphia is ~129 km
        self.assertTrue(is_within_distance(
            40.7128, -74.0060, 39.9526, -75.1652, 150000
        ))
        self.assertFalse(is_within_distance(
            40.7128, -74.0060, 39.9526, -75.1652, 100000
        ))
    
    def test_nyc_to_philadelphia(self):
        """Test known distance: NYC to Philadelphia."""
        # Known distance: ~129 km
        d_hav = haversine_distance(40.7128, -74.0060, 39.9526, -75.1652)
        d_vin = vincenty_distance(40.7128, -74.0060, 39.9526, -75.1652)
        
        # Both should be close to 129 km
        self.assertGreater(d_hav, 128000)
        self.assertLess(d_hav, 130000)
        self.assertGreater(d_vin, 128000)
        self.assertLess(d_vin, 130000)


# =============================================================================
# Geohash Tests
# =============================================================================

class TestGeohashUtils(unittest.TestCase):
    """Test geohash encoding and utilities."""
    
    def test_encode_decode_roundtrip(self):
        """Test geohash encode/decode roundtrip."""
        test_points = [
            (40.7128, -74.0060),  # NYC
            (51.5074, -0.1278),   # London
            (35.6762, 139.6503),  # Tokyo
            (0.0, 0.0),           # Null Island
            (-33.8688, 151.2093), # Sydney
        ]
        
        for lat, lon in test_points:
            for precision in [4, 6, 8]:
                geohash = encode_geohash(lat, lon, precision)
                decoded_lat, decoded_lon, lat_err, lon_err = decode_geohash(geohash)
                
                # Decoded point should be within error bounds
                self.assertLess(abs(lat - decoded_lat), lat_err * 2)
                self.assertLess(abs(lon - decoded_lon), lon_err * 2)
    
    def test_encode_precision(self):
        """Test that encoding produces correct length."""
        for precision in range(1, 13):
            geohash = encode_geohash(40.7128, -74.0060, precision)
            self.assertEqual(len(geohash), precision)
    
    def test_invalid_geohash_characters(self):
        """Test that invalid characters raise error."""
        with self.assertRaises(ValueError):
            decode_geohash('invalid')  # 'i' and 'l' are invalid
        
        with self.assertRaises(ValueError):
            decode_geohash('abcao')  # 'a' and 'o' are invalid
    
    def test_get_neighbors(self):
        """Test neighbor calculation."""
        geohash = 'dr5r7y'
        neighbors = get_neighbors(geohash)
        
        # Should have 8 neighbors
        self.assertEqual(len(neighbors), 8)
        self.assertIn('n', neighbors)
        self.assertIn('ne', neighbors)
        self.assertIn('e', neighbors)
        self.assertIn('se', neighbors)
        self.assertIn('s', neighbors)
        self.assertIn('sw', neighbors)
        self.assertIn('w', neighbors)
        self.assertIn('nw', neighbors)
        
        # All neighbors should be valid geohashes
        for direction, neighbor in neighbors.items():
            self.assertEqual(len(neighbor), len(geohash))
            # Should be able to decode
            decode_geohash(neighbor)
    
    def test_geohash_to_bbox(self):
        """Test bounding box conversion."""
        geohash = 'dr5r7y'
        min_lat, min_lon, max_lat, max_lon = geohash_to_bbox(geohash)
        
        # Center point should be within bbox
        center_lat, center_lon, _, _ = decode_geohash(geohash)
        self.assertGreaterEqual(center_lat, min_lat)
        self.assertLessEqual(center_lat, max_lat)
        self.assertGreaterEqual(center_lon, min_lon)
        self.assertLessEqual(center_lon, max_lon)
        
        # Bbox should have positive dimensions
        self.assertGreater(max_lat, min_lat)
        self.assertGreater(max_lon, min_lon)
    
    def test_bbox_to_geohashes(self):
        """Test bbox to geohash list conversion."""
        # Small bbox around NYC
        geohashes = bbox_to_geohashes(40.7, -74.1, 40.8, -74.0, precision=5)
        
        # Should return multiple geohashes
        self.assertGreater(len(geohashes), 0)
        
        # All should be valid
        for gh in geohashes:
            self.assertEqual(len(gh), 5)
            decode_geohash(gh)
    
    def test_get_geohashes_in_radius(self):
        """Test geohash radius query."""
        # NYC with 1km radius
        geohashes = get_geohashes_in_radius(40.7128, -74.0060, 1000, precision=7)
        
        self.assertGreater(len(geohashes), 0)
        
        # All returned geohashes should be roughly within radius
        for gh in geohashes:
            gh_lat, gh_lon, _, _ = decode_geohash(gh)
            from distance import haversine_distance
            d = haversine_distance(40.7128, -74.0060, gh_lat, gh_lon)
            # Allow some margin for cell size
            self.assertLess(d, 2000)
    
    def test_get_common_prefix(self):
        """Test common prefix extraction."""
        self.assertEqual(get_common_prefix('dr5r7y', 'dr5r7z'), 'dr5r7')
        self.assertEqual(get_common_prefix('dr5r7y', 'dr5rk'), 'dr5r')
        self.assertEqual(get_common_prefix('dr5r7y', 'dr5r7y'), 'dr5r7y')
        self.assertEqual(get_common_prefix('abc', 'xyz'), '')
    
    def test_get_precision_for_radius(self):
        """Test precision recommendation for radius."""
        # Larger radius should give lower precision
        self.assertLess(get_precision_for_radius(10000), get_precision_for_radius(100))
        
        # 1 km should give precision 6 or 7
        self.assertIn(get_precision_for_radius(1000), [6, 7])
    
    def test_are_neighbors(self):
        """Test neighbor detection."""
        # These should be neighbors
        self.assertTrue(are_neighbors('dr5r7y', 'dr5r7z'))
        
        # These should not be neighbors
        self.assertFalse(are_neighbors('dr5r7y', 'dr5rk'))
        
        # Different lengths can't be neighbors
        self.assertFalse(are_neighbors('dr5r7y', 'dr5r7'))
    
    def test_get_parent(self):
        """Test parent geohash extraction."""
        self.assertEqual(get_parent('dr5r7y'), 'dr5r7')
        self.assertEqual(get_parent('dr5r7'), 'dr5r')
        self.assertIsNone(get_parent('d'))
    
    def test_get_children(self):
        """Test child geohash generation."""
        children = get_children('dr5r7')
        
        # Should have 32 children
        self.assertEqual(len(children), 32)
        
        # All should start with parent
        for child in children:
            self.assertTrue(child.startswith('dr5r7'))
            self.assertEqual(len(child), 6)
    
    def test_get_geohash_area(self):
        """Test geohash area calculation."""
        # Area should be positive
        area = get_geohash_area('dr5r7y')
        self.assertGreater(area, 0)
        
        # Higher precision should give smaller area
        area_6 = get_geohash_area('dr5r7y')
        area_5 = get_geohash_area('dr5r7')
        self.assertLess(area_6, area_5)
    
    def test_vectorized_encode(self):
        """Test vectorized geohash encoding."""
        lats = np.array([40.71, 40.72])
        lons = np.array([-74.01, -74.02])
        
        geohashes = encode_geohash_vectorized(lats, lons, precision=6)
        
        self.assertEqual(len(geohashes), 2)
        self.assertEqual(len(geohashes[0]), 6)
        self.assertEqual(len(geohashes[1]), 6)


# =============================================================================
# Edge Case and Integration Tests
# =============================================================================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""
    
    def test_equator_points(self):
        """Test calculations at the equator."""
        lat, lon, elev = 0.0, 0.0, 0.0
        
        # ENU conversion
        e, n, u = wgs84_to_enu(lat, lon, elev, lat, lon, elev)
        self.assertAlmostEqual(e, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(n, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(u, 0.0, delta=TOLERANCE_MM)
        
        # Distance
        d = haversine_distance(0, 0, 0, 1)
        self.assertAlmostEqual(d, EARTH_MEAN_RADIUS * math.radians(1), delta=100)
    
    def test_pole_points(self):
        """Test calculations at the poles."""
        # North Pole
        x, y, z = wgs84_to_ecef(90.0, 0.0, 0.0)
        self.assertAlmostEqual(z, WGS84_B, delta=TOLERANCE_M)
        
        # South Pole
        x, y, z = wgs84_to_ecef(-90.0, 0.0, 0.0)
        self.assertAlmostEqual(z, -WGS84_B, delta=TOLERANCE_M)
        
        # ECEF to WGS84 at pole
        lat, lon, elev = ecef_to_wgs84(0, 0, WGS84_B)
        self.assertAlmostEqual(lat, 90.0, delta=TOLERANCE_DEG)
    
    def test_antimeridian(self):
        """Test calculations across the antimeridian."""
        # Points on either side of antimeridian
        lat, elev = 0.0, 0.0
        lon1, lon2 = 179.9, -179.9
        
        # Distance should be small (~0.2°)
        d = haversine_distance(lat, lon1, lat, lon2)
        expected = EARTH_MEAN_RADIUS * math.radians(0.2)
        self.assertAlmostEqual(d, expected, delta=1000)
    
    def test_numerical_stability(self):
        """Test numerical stability for various inputs."""
        # Very small distances
        d = haversine_distance(40.0, -74.0, 40.000001, -74.0)
        self.assertGreater(d, 0)
        self.assertTrue(math.isfinite(d))
        
        # Very close ENU points
        e, n, u = wgs84_to_enu(40.0, -74.0, 0.0, 40.0, -74.0, 0.0)
        self.assertAlmostEqual(e, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(n, 0.0, delta=TOLERANCE_MM)
        self.assertAlmostEqual(u, 0.0, delta=TOLERANCE_MM)
    
    def test_large_elevation_differences(self):
        """Test with large elevation differences."""
        # Ground to high altitude
        e, n, u = wgs84_to_enu(40.0, -74.0, 10000.0, 40.0, -74.0, 0.0)
        self.assertAlmostEqual(u, 10000.0, delta=TOLERANCE_M)
        
        # Elevation angle
        el = calculate_elevation_angle(1000, 10000)
        self.assertAlmostEqual(el, 84.29, delta=0.01)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    # Run all tests
    unittest.main(verbosity=2)