#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkSpot Ray-Casting Engine Unit Tests

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

Unit tests for the ray-casting obstruction algorithm.

Test Categories:
1. ENU Coordinate Tests - Verify WGS84 <-> ENU transformations
2. Azimuth/Elevation Tests - Verify angle calculations
3. Obstruction Profile Tests - Verify building silhouette computation
4. Satellite Intersection Tests - Verify LOS determination
5. Zone Classification Tests - Verify GREEN/AMBER/DEAD classification
6. Grid Analysis Tests - Verify grid generation and parallel processing
7. Performance Tests - Verify timing requirements

Run with: python -m pytest test_ray_casting.py -v
"""

import unittest
import numpy as np
from datetime import datetime
from typing import List, Dict, Any
import time

# Import modules under test
from enu_utils import (
    wgs84_to_enu,
    enu_to_wgs84,
    calculate_azimuth,
    calculate_elevation_angle,
    azimuth_to_sector_index,
    sector_index_to_azimuth,
    calculate_horizontal_distance,
    is_within_radius
)

from ray_casting_engine import (
    ObstructionEngine,
    AnalysisResult,
    Satellite,
    Zone,
    MockSatelliteEngine,
    MockDataPipeline
)

from grid_analyzer import (
    GridAnalyzer,
    GridPoint,
    GridResult,
    create_grid_analyzer
)


# =============================================================================
# ENU Coordinate Tests
# =============================================================================

class TestENUCoordinates(unittest.TestCase):
    """Test ENU coordinate transformations."""
    
    def test_wgs84_to_enu_origin(self):
        """Test that reference point converts to (0, 0, 0) in ENU."""
        lat, lon, elev = 40.7128, -74.0060, 10.0
        e, n, u = wgs84_to_enu(lat, lon, elev, lat, lon, elev)
        
        self.assertAlmostEqual(e, 0.0, places=6)
        self.assertAlmostEqual(n, 0.0, places=6)
        self.assertAlmostEqual(u, 0.0, places=6)
    
    def test_wgs84_to_enu_north(self):
        """Test that point north of reference has positive N coordinate."""
        ref_lat, ref_lon = 40.7128, -74.0060
        # Point 100m north (approx 0.0009 degrees latitude)
        lat = ref_lat + 0.0009
        lon = ref_lon
        
        e, n, u = wgs84_to_enu(lat, lon, 0.0, ref_lat, ref_lon, 0.0)
        
        # Should be approximately 100m north, 0m east
        self.assertGreater(n, 90.0)
        self.assertLess(n, 110.0)
        self.assertAlmostEqual(e, 0.0, delta=5.0)  # Allow some error due to curvature
    
    def test_wgs84_to_enu_east(self):
        """Test that point east of reference has positive E coordinate."""
        ref_lat, ref_lon = 40.7128, -74.0060
        # Point 100m east (longitude varies with latitude)
        lat = ref_lat
        lon = ref_lon + 0.0012  # Approx 100m at this latitude
        
        e, n, u = wgs84_to_enu(lat, lon, 0.0, ref_lat, ref_lon, 0.0)
        
        # Should be approximately 0m north, 100m east
        self.assertGreater(e, 90.0)
        self.assertLess(e, 110.0)
        self.assertAlmostEqual(n, 0.0, delta=5.0)
    
    def test_enu_to_wgs84_roundtrip(self):
        """Test that ENU -> WGS84 -> ENU is identity."""
        ref_lat, ref_lon, ref_elev = 40.7128, -74.0060, 10.0
        
        # Test points at various ENU offsets
        test_offsets = [
            (100, 0, 0),    # 100m east
            (0, 100, 0),    # 100m north
            (100, 100, 10), # 100m east, 100m north, 10m up
            (-50, -50, -5), # Negative offsets
        ]
        
        for e, n, u in test_offsets:
            # ENU -> WGS84
            lat, lon, elev = enu_to_wgs84(e, n, u, ref_lat, ref_lon, ref_elev)
            
            # WGS84 -> ENU
            e2, n2, u2 = wgs84_to_enu(lat, lon, elev, ref_lat, ref_lon, ref_elev)
            
            # Should be approximately equal (small error due to Earth curvature)
            self.assertAlmostEqual(e, e2, delta=0.1)
            self.assertAlmostEqual(n, n2, delta=0.1)
            self.assertAlmostEqual(u, u2, delta=0.1)
    
    def test_vectorized_operations(self):
        """Test that ENU functions work with arrays."""
        ref_lat, ref_lon = 40.7128, -74.0060
        
        # Create arrays of points
        lats = np.array([ref_lat, ref_lat + 0.001, ref_lat + 0.002])
        lons = np.array([ref_lon, ref_lon, ref_lon])
        elevs = np.array([0.0, 10.0, 20.0])
        
        e, n, u = wgs84_to_enu(lats, lons, elevs, ref_lat, ref_lon, 0.0)
        
        # Should return arrays of same length
        self.assertEqual(len(e), 3)
        self.assertEqual(len(n), 3)
        self.assertEqual(len(u), 3)
        
        # First point should be at origin
        self.assertAlmostEqual(e[0], 0.0, places=6)
        self.assertAlmostEqual(n[0], 0.0, places=6)


# =============================================================================
# Azimuth and Elevation Tests
# =============================================================================

class TestAzimuthElevation(unittest.TestCase):
    """Test azimuth and elevation angle calculations."""
    
    def test_azimuth_north(self):
        """Test azimuth to point directly north."""
        az = calculate_azimuth(0, 0, 0, 100)
        self.assertAlmostEqual(az, 0.0, places=6)
    
    def test_azimuth_east(self):
        """Test azimuth to point directly east."""
        az = calculate_azimuth(0, 0, 100, 0)
        self.assertAlmostEqual(az, 90.0, places=6)
    
    def test_azimuth_south(self):
        """Test azimuth to point directly south."""
        az = calculate_azimuth(0, 0, 0, -100)
        self.assertAlmostEqual(az, 180.0, places=6)
    
    def test_azimuth_west(self):
        """Test azimuth to point directly west."""
        az = calculate_azimuth(0, 0, -100, 0)
        self.assertAlmostEqual(az, 270.0, places=6)
    
    def test_azimuth_northeast(self):
        """Test azimuth to point northeast."""
        az = calculate_azimuth(0, 0, 100, 100)
        self.assertAlmostEqual(az, 45.0, places=6)
    
    def test_azimuth_vectorized(self):
        """Test that azimuth calculation works with arrays."""
        e1 = np.array([0, 0, 0])
        n1 = np.array([0, 0, 0])
        e2 = np.array([0, 100, 100])
        n2 = np.array([100, 0, 100])
        
        azimuths = calculate_azimuth(e1, n1, e2, n2)
        
        expected = np.array([0.0, 90.0, 45.0])
        np.testing.assert_array_almost_equal(azimuths, expected, decimal=6)
    
    def test_elevation_angle_flat(self):
        """Test elevation angle to point at same height."""
        el = calculate_elevation_angle(100, 0)
        self.assertAlmostEqual(el, 0.0, places=6)
    
    def test_elevation_angle_up(self):
        """Test elevation angle to point above."""
        el = calculate_elevation_angle(100, 100)
        self.assertAlmostEqual(el, 45.0, places=6)
    
    def test_elevation_angle_down(self):
        """Test elevation angle to point below."""
        el = calculate_elevation_angle(100, -100)
        self.assertAlmostEqual(el, -45.0, places=6)
    
    def test_elevation_angle_vertical(self):
        """Test elevation angle to point directly above."""
        el = calculate_elevation_angle(0.001, 100)
        self.assertAlmostEqual(el, 90.0, places=1)
    
    def test_elevation_angle_vectorized(self):
        """Test that elevation calculation works with arrays."""
        dists = np.array([100, 100, 100])
        heights = np.array([0, 100, -100])
        
        elevations = calculate_elevation_angle(dists, heights)
        
        expected = np.array([0.0, 45.0, -45.0])
        np.testing.assert_array_almost_equal(elevations, expected, decimal=6)


# =============================================================================
# Sector Index Tests
# =============================================================================

class TestSectorIndices(unittest.TestCase):
    """Test azimuth sector index conversions."""
    
    def test_sector_index_2_degree(self):
        """Test sector indexing with 2-degree sectors."""
        # Sector 0: 0-2 degrees
        self.assertEqual(azimuth_to_sector_index(0.0, 2.0), 0)
        self.assertEqual(azimuth_to_sector_index(1.0, 2.0), 0)
        self.assertEqual(azimuth_to_sector_index(1.9, 2.0), 0)
        
        # Sector 1: 2-4 degrees
        self.assertEqual(azimuth_to_sector_index(2.0, 2.0), 1)
        self.assertEqual(azimuth_to_sector_index(3.0, 2.0), 1)
        
        # Sector 90: 180-182 degrees
        self.assertEqual(azimuth_to_sector_index(180.0, 2.0), 90)
        
        # Sector 179: 358-360 degrees
        self.assertEqual(azimuth_to_sector_index(358.0, 2.0), 179)
        self.assertEqual(azimuth_to_sector_index(359.0, 2.0), 179)
    
    def test_sector_index_wraparound(self):
        """Test that 360 degrees wraps to sector 0."""
        self.assertEqual(azimuth_to_sector_index(360.0, 2.0), 0)
        self.assertEqual(azimuth_to_sector_index(720.0, 2.0), 0)
    
    def test_sector_index_negative(self):
        """Test that negative azimuths wrap correctly."""
        self.assertEqual(azimuth_to_sector_index(-1.0, 2.0), 179)
        self.assertEqual(azimuth_to_sector_index(-90.0, 2.0), 135)
    
    def test_sector_to_azimuth(self):
        """Test conversion from sector index to azimuth."""
        self.assertEqual(sector_index_to_azimuth(0, 2.0), 1.0)   # Center of 0-2
        self.assertEqual(sector_index_to_azimuth(1, 2.0), 3.0)   # Center of 2-4
        self.assertEqual(sector_index_to_azimuth(90, 2.0), 181.0)  # Center of 180-182
        self.assertEqual(sector_index_to_azimuth(179, 2.0), 359.0)  # Center of 358-360
    
    def test_sector_roundtrip(self):
        """Test that sector -> azimuth -> sector is identity."""
        for sector in range(180):
            azimuth = sector_index_to_azimuth(sector, 2.0)
            sector2 = azimuth_to_sector_index(azimuth, 2.0)
            self.assertEqual(sector, sector2)


# =============================================================================
# Obstruction Engine Tests
# =============================================================================

class MockSatelliteEngineForTests:
    """Mock satellite engine with configurable output."""
    
    def __init__(self, satellites: List[Dict[str, Any]] = None):
        self.satellites = satellites or []
    
    def get_visible_satellites(self, lat, lon, elevation, timestamp, min_elevation):
        return [s for s in self.satellites if s['elevation'] >= min_elevation]


class MockDataPipelineForTests:
    """Mock data pipeline with configurable building data."""
    
    def __init__(self, buildings: List[Dict[str, Any]] = None):
        self.buildings = buildings or []
    
    def get_buildings_in_radius(self, lat, lon, radius_m):
        return self.buildings


class TestObstructionEngine(unittest.TestCase):
    """Test the obstruction engine core functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create mock engines
        self.sat_engine = MockSatelliteEngineForTests()
        self.data_pipeline = MockDataPipelineForTests()
        
        # Create obstruction engine
        self.engine = ObstructionEngine(
            satellite_engine=self.sat_engine,
            data_pipeline=self.data_pipeline,
            min_elevation=25.0,
            sat_threshold=4
        )
    
    def test_clear_sky_no_buildings(self):
        """Test that clear sky with no buildings gives GREEN zone."""
        # Set up 8 satellites above min elevation
        self.sat_engine.satellites = [
            {'prn': f'G{i:02d}', 'azimuth': i * 45, 'elevation': 45.0, 'system': 'GPS'}
            for i in range(8)
        ]
        
        # No buildings
        self.data_pipeline.buildings = []
        
        result = self.engine.analyze_position(40.7128, -74.0060, 0.0)
        
        self.assertEqual(result.zone, Zone.GREEN)
        self.assertEqual(result.n_clear, 8)
        self.assertEqual(result.n_total, 8)
        self.assertEqual(result.obstruction_pct, 0.0)
    
    def test_blocking_building(self):
        """Test that a tall building blocks satellites in its sector."""
        # Satellite at azimuth 45°, elevation 30°
        self.sat_engine.satellites = [
            {'prn': 'G01', 'azimuth': 45.0, 'elevation': 30.0, 'system': 'GPS'}
        ]
        
        # Building at azimuth 45°, 50m away, 40m tall
        # Elevation angle to building top: atan2(40, 50) = 38.7°
        # This should block the satellite at 30° elevation
        self.data_pipeline.buildings = [
            {
                'lat': 40.7132,  # Approx 50m north-east
                'lon': -74.0055,
                'ground_elevation': 0.0,
                'height': 40.0
            }
        ]
        
        result = self.engine.analyze_position(40.7128, -74.0060, 0.0)
        
        # Satellite should be blocked
        self.assertEqual(result.n_clear, 0)
        self.assertEqual(result.zone, Zone.DEAD)
    
    def test_partial_building_block(self):
        """Test partial blocking where some satellites are blocked."""
        # Satellites at various azimuths
        self.sat_engine.satellites = [
            {'prn': 'G01', 'azimuth': 0.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G02', 'azimuth': 45.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G03', 'azimuth': 90.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G04', 'azimuth': 135.0, 'elevation': 45.0, 'system': 'GPS'},
        ]
        
        # Building blocking only azimuth 45°
        self.data_pipeline.buildings = [
            {
                'lat': 40.7132,
                'lon': -74.0055,
                'ground_elevation': 0.0,
                'height': 60.0  # Tall enough to block
            }
        ]
        
        result = self.engine.analyze_position(40.7128, -74.0060, 0.0)
        
        # 3 satellites should be clear, 1 blocked
        self.assertEqual(result.n_clear, 3)
        self.assertEqual(result.n_total, 4)
        self.assertEqual(result.zone, Zone.AMBER)
    
    def test_zone_classification_green(self):
        """Test GREEN zone classification."""
        self.assertEqual(self.engine.classify_zone(4), Zone.GREEN)
        self.assertEqual(self.engine.classify_zone(8), Zone.GREEN)
        self.assertEqual(self.engine.classify_zone(12), Zone.GREEN)
    
    def test_zone_classification_amber(self):
        """Test AMBER zone classification."""
        self.assertEqual(self.engine.classify_zone(2), Zone.AMBER)
        self.assertEqual(self.engine.classify_zone(3), Zone.AMBER)
    
    def test_zone_classification_dead(self):
        """Test DEAD zone classification."""
        self.assertEqual(self.engine.classify_zone(0), Zone.DEAD)
        self.assertEqual(self.engine.classify_zone(1), Zone.DEAD)
    
    def test_obstruction_percentage(self):
        """Test obstruction percentage calculation."""
        # 180 sectors total
        self.assertEqual(self.engine.calculate_obstruction_percentage(0), 0.0)
        self.assertEqual(self.engine.calculate_obstruction_percentage(90), 50.0)
        self.assertEqual(self.engine.calculate_obstruction_percentage(180), 100.0)
    
    def test_no_visible_satellites(self):
        """Test behavior when no satellites are visible."""
        self.sat_engine.satellites = []
        
        result = self.engine.analyze_position(40.7128, -74.0060, 0.0)
        
        self.assertEqual(result.zone, Zone.DEAD)
        self.assertEqual(result.n_clear, 0)
        self.assertEqual(result.n_total, 0)


# =============================================================================
# Grid Analyzer Tests
# =============================================================================

class TestGridAnalyzer(unittest.TestCase):
    """Test grid analysis functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        sat_engine = MockSatelliteEngine(n_satellites=8)
        data_pipeline = MockDataPipeline(n_buildings=20)
        
        self.engine = ObstructionEngine(
            satellite_engine=sat_engine,
            data_pipeline=data_pipeline,
            min_elevation=25.0,
            sat_threshold=4
        )
        
        self.analyzer = GridAnalyzer(self.engine, n_workers=2)
    
    def test_create_grid(self):
        """Test grid creation."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        # 100m / 50m = 2 intervals + 1 = 3 points per dimension
        # 3 x 3 = 9 points
        self.assertEqual(len(grid), 9)
        
        # Check that center point is at reference
        center = grid[4]  # Middle of 3x3 grid
        self.assertAlmostEqual(center.lat, 40.7128, places=4)
        self.assertAlmostEqual(center.lon, -74.0060, places=4)
    
    def test_grid_indices(self):
        """Test that grid indices are correct."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        # Check row-major ordering
        expected_indices = [
            (0, 0), (0, 1), (0, 2),
            (1, 0), (1, 1), (1, 2),
            (2, 0), (2, 1), (2, 2)
        ]
        
        for point, expected in zip(grid, expected_indices):
            self.assertEqual((point.grid_i, point.grid_j), expected)
    
    def test_analyze_grid(self):
        """Test grid analysis."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        results = self.analyzer.analyze_grid(grid, parallel=False)
        
        self.assertEqual(len(results), len(grid))
        
        # All results should have valid zones
        for result in results:
            self.assertIn(result.zone, [Zone.GREEN, Zone.AMBER, Zone.DEAD])
            self.assertIsNotNone(result.analysis)
    
    def test_grid_to_geojson(self):
        """Test GeoJSON export."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        results = self.analyzer.analyze_grid(grid, parallel=False)
        geojson = self.analyzer.grid_to_geojson(results)
        
        # Check GeoJSON structure
        self.assertEqual(geojson['type'], 'FeatureCollection')
        self.assertIn('features', geojson)
        self.assertEqual(len(geojson['features']), len(grid))
        
        # Check first feature
        feature = geojson['features'][0]
        self.assertEqual(feature['type'], 'Feature')
        self.assertEqual(feature['geometry']['type'], 'Point')
        self.assertIn('properties', feature)
        self.assertIn('zone', feature['properties'])
    
    def test_grid_to_heatmap_array(self):
        """Test heat map array conversion."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        results = self.analyzer.analyze_grid(grid, parallel=False)
        heatmap = self.analyzer.grid_to_heatmap_array(results)
        
        # Should be 3x3 array
        self.assertEqual(heatmap.shape, (3, 3))
        
        # All values should be 0, 1, or 2
        self.assertTrue(np.all((heatmap >= 0) & (heatmap <= 2)))
    
    def test_coverage_statistics(self):
        """Test coverage statistics calculation."""
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=100,
            spacing_m=50
        )
        
        results = self.analyzer.analyze_grid(grid, parallel=False)
        stats = self.analyzer.get_coverage_statistics(results)
        
        self.assertIn('total_points', stats)
        self.assertIn('zone_counts', stats)
        self.assertIn('zone_percentages', stats)
        self.assertIn('satellite_stats', stats)
        
        self.assertEqual(stats['total_points'], 9)
        self.assertEqual(sum(stats['zone_counts'].values()), 9)


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance(unittest.TestCase):
    """Test performance requirements."""
    
    def setUp(self):
        """Set up test fixtures."""
        sat_engine = MockSatelliteEngine(n_satellites=12)
        data_pipeline = MockDataPipeline(n_buildings=50)
        
        self.engine = ObstructionEngine(
            satellite_engine=sat_engine,
            data_pipeline=data_pipeline,
            min_elevation=25.0,
            sat_threshold=4
        )
        
        self.analyzer = GridAnalyzer(self.engine, n_workers=4)
    
    def test_single_position_performance(self):
        """Test that single position analysis is under 50ms."""
        lat, lon, elev = 40.7128, -74.0060, 10.0
        
        # Warm up
        for _ in range(3):
            self.engine.analyze_position(lat, lon, elev)
        
        # Time the analysis
        times = []
        for _ in range(10):
            start = time.perf_counter()
            result = self.engine.analyze_position(lat, lon, elev)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
        
        avg_time = np.mean(times)
        max_time = np.max(times)
        
        print(f"\nSingle position performance:")
        print(f"  Average: {avg_time:.2f}ms")
        print(f"  Max: {max_time:.2f}ms")
        
        # Should be under 50ms on average (allow some variance)
        self.assertLess(avg_time, 50.0, f"Average time {avg_time:.2f}ms exceeds 50ms target")
    
    def test_grid_performance(self):
        """Test that 500m² grid analysis is under 2 seconds."""
        # Create ~320 point grid (500m / 28m ≈ 18 points per dimension)
        grid = self.analyzer.create_analysis_grid(
            center_lat=40.7128,
            center_lon=-74.0060,
            size_m=500,
            spacing_m=28
        )
        
        print(f"\nGrid size: {len(grid)} points ({int(np.sqrt(len(grid)))}x{int(np.sqrt(len(grid)))})")
        
        # Time the analysis
        start = time.perf_counter()
        results = self.analyzer.analyze_grid(grid, parallel=True)
        elapsed = (time.perf_counter() - start) * 1000
        
        print(f"Grid analysis time: {elapsed:.1f}ms")
        print(f"Time per point: {elapsed/len(grid):.1f}ms")
        
        # Should be under 2 seconds (2000ms)
        self.assertLess(elapsed, 2000.0, f"Grid analysis {elapsed:.1f}ms exceeds 2s target")


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration(unittest.TestCase):
    """Integration tests with realistic scenarios."""
    
    def test_urban_canyon_scenario(self):
        """Test scenario with tall buildings on both sides (urban canyon)."""
        # Create satellite engine with satellites at various elevations
        sat_engine = MockSatelliteEngineForTests([
            {'prn': 'G01', 'azimuth': 0.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G02', 'azimuth': 45.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G03', 'azimuth': 90.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G04', 'azimuth': 135.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G05', 'azimuth': 180.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G06', 'azimuth': 225.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G07', 'azimuth': 270.0, 'elevation': 45.0, 'system': 'GPS'},
            {'prn': 'G08', 'azimuth': 315.0, 'elevation': 45.0, 'system': 'GPS'},
        ])
        
        # Create buildings forming an urban canyon (tall buildings east and west)
        buildings = []
        
        # Buildings to the east (azimuth ~90°)
        for i in range(5):
            buildings.append({
                'lat': 40.7128,
                'lon': -74.0050 + i * 0.0001,
                'ground_elevation': 0.0,
                'height': 80.0  # Tall building
            })
        
        # Buildings to the west (azimuth ~270°)
        for i in range(5):
            buildings.append({
                'lat': 40.7128,
                'lon': -74.0070 - i * 0.0001,
                'ground_elevation': 0.0,
                'height': 80.0  # Tall building
            })
        
        data_pipeline = MockDataPipelineForTests(buildings)
        
        engine = ObstructionEngine(
            satellite_engine=sat_engine,
            data_pipeline=data_pipeline,
            min_elevation=25.0,
            sat_threshold=4
        )
        
        result = engine.analyze_position(40.7128, -74.0060, 0.0)
        
        # Satellites at 90° and 270° should be blocked
        # 6 satellites should be clear
        self.assertEqual(result.n_clear, 6)
        self.assertEqual(result.n_total, 8)
        self.assertEqual(result.zone, Zone.GREEN)
    
    def test_open_area_scenario(self):
        """Test scenario with no buildings (open parking lot)."""
        sat_engine = MockSatelliteEngineForTests([
            {'prn': f'G{i:02d}', 'azimuth': i * 30, 'elevation': 50.0, 'system': 'GPS'}
            for i in range(12)
        ])
        
        # No buildings
        data_pipeline = MockDataPipelineForTests([])
        
        engine = ObstructionEngine(
            satellite_engine=sat_engine,
            data_pipeline=data_pipeline,
            min_elevation=25.0,
            sat_threshold=4
        )
        
        result = engine.analyze_position(40.7128, -74.0060, 0.0)
        
        # All satellites should be clear
        self.assertEqual(result.n_clear, 12)
        self.assertEqual(result.n_total, 12)
        self.assertEqual(result.zone, Zone.GREEN)
        self.assertEqual(result.obstruction_pct, 0.0)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Run all tests
    unittest.main(verbosity=2)
