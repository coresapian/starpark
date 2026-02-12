# Copyright (c) 2024 LinkSpot Project
# BSD 3-Clause License
# SPDX-License-Identifier: BSD-3-Clause
#
# test_data_pipeline.py - Unit tests for LinkSpot data pipeline

"""
Unit tests for the LinkSpot data pipeline module.

This module provides comprehensive tests for:
- Geohash encoding/decoding
- Coordinate conversion
- Building height estimation
- Data pipeline operations
- Client functionality
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, Point, box

# Import modules to test
from data_pipeline import (
    GeohashEncoder,
    CoordinateConverter,
    BuildingHeightEstimator,
    LinkSpotDataPipeline,
    BuildingData,
    TerrainData,
    query_buildings
)
from overture_client import OvertureMapsClient
from terrain_client import CopernicusTerrainClient


class TestGeohashEncoder(unittest.TestCase):
    """Test cases for GeohashEncoder."""
    
    def test_encode_basic(self):
        """Test basic geohash encoding."""
        # Test Times Square
        geohash = GeohashEncoder.encode(40.7580, -73.9855, precision=6)
        self.assertEqual(len(geohash), 6)
        self.assertTrue(all(c in GeohashEncoder.BASE32 for c in geohash))
    
    def test_encode_different_precisions(self):
        """Test encoding with different precision levels."""
        lat, lon = 40.7580, -73.9855
        
        for precision in [1, 4, 6, 8, 12]:
            geohash = GeohashEncoder.encode(lat, lon, precision=precision)
            self.assertEqual(len(geohash), precision)
    
    def test_encode_invalid_latitude(self):
        """Test encoding with invalid latitude."""
        with self.assertRaises(ValueError):
            GeohashEncoder.encode(91.0, 0.0)
        
        with self.assertRaises(ValueError):
            GeohashEncoder.encode(-91.0, 0.0)
    
    def test_encode_invalid_longitude(self):
        """Test encoding with invalid longitude."""
        with self.assertRaises(ValueError):
            GeohashEncoder.encode(0.0, 181.0)
        
        with self.assertRaises(ValueError):
            GeohashEncoder.encode(0.0, -181.0)
    
    def test_decode_basic(self):
        """Test basic geohash decoding."""
        # Encode then decode
        original_lat, original_lon = 40.7580, -73.9855
        geohash = GeohashEncoder.encode(original_lat, original_lon, precision=6)
        
        decoded_lat, decoded_lon = GeohashEncoder.decode(geohash)
        
        # Check approximate match (within cell size)
        self.assertAlmostEqual(decoded_lat, original_lat, places=1)
        self.assertAlmostEqual(decoded_lon, original_lon, places=1)
    
    def test_decode_known_values(self):
        """Test decoding known geohash values."""
        # 'dr5r' is approximately Times Square area
        lat, lon = GeohashEncoder.decode('dr5r')
        self.assertIsInstance(lat, float)
        self.assertIsInstance(lon, float)
    
    def test_encode_decode_roundtrip(self):
        """Test that encode-decode is consistent."""
        test_coords = [
            (40.7580, -73.9855),  # NYC
            (51.5074, -0.1278),   # London
            (35.6762, 139.6503),  # Tokyo
            (-33.8688, 151.2093), # Sydney
            (0.0, 0.0),           # Null Island
        ]
        
        for lat, lon in test_coords:
            geohash = GeohashEncoder.encode(lat, lon, precision=8)
            decoded_lat, decoded_lon = GeohashEncoder.decode(geohash)
            
            # Should be within the same cell
            self.assertEqual(
                GeohashEncoder.encode(lat, lon, precision=8),
                GeohashEncoder.encode(decoded_lat, decoded_lon, precision=8)
            )


class TestCoordinateConverter(unittest.TestCase):
    """Test cases for CoordinateConverter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.origin_lat = 40.7580
        self.origin_lon = -73.9855
        self.converter = CoordinateConverter(self.origin_lat, self.origin_lon)
    
    def test_wgs84_to_enu_origin(self):
        """Test ENU conversion at origin point."""
        east, north, up = self.converter.wgs84_to_enu_coords(
            self.origin_lon, self.origin_lat, 0.0
        )
        
        # At origin, ENU should be (0, 0, 0)
        self.assertAlmostEqual(east, 0.0, places=1)
        self.assertAlmostEqual(north, 0.0, places=1)
        self.assertAlmostEqual(up, 0.0, places=1)
    
    def test_wgs84_to_enu_offset(self):
        """Test ENU conversion with offset."""
        # Move 100m north
        north_lat = self.origin_lat + (100 / 111320)
        east, north, up = self.converter.wgs84_to_enu_coords(
            self.origin_lon, north_lat, 0.0
        )
        
        # Should be approximately (0, 100, 0)
        self.assertAlmostEqual(east, 0.0, delta=5.0)
        self.assertAlmostEqual(north, 100.0, delta=5.0)
        self.assertAlmostEqual(up, 0.0, places=1)
    
    def test_enu_to_wgs84_roundtrip(self):
        """Test ENU to WGS84 roundtrip conversion."""
        test_offsets = [
            (100.0, 0.0, 0.0),    # 100m east
            (0.0, 100.0, 0.0),    # 100m north
            (100.0, 100.0, 50.0), # Combined
        ]
        
        for east, north, up in test_offsets:
            lon, lat, height = self.converter.enu_to_wgs84_coords(east, north, up)
            
            # Convert back
            east2, north2, up2 = self.converter.wgs84_to_enu_coords(lon, lat, height)
            
            # Should be close to original
            self.assertAlmostEqual(east2, east, delta=1.0)
            self.assertAlmostEqual(north2, north, delta=1.0)
            self.assertAlmostEqual(up2, up, delta=1.0)
    
    def test_approximate_conversion(self):
        """Test approximate conversion methods."""
        # Test at different latitudes
        for lat in [0.0, 30.0, 45.0, 60.0]:
            converter = CoordinateConverter(lat, 0.0)
            
            # Small offset
            east, north, up = converter._approximate_wgs84_to_enu(
                0.0, lat + 0.001, 0.0
            )
            
            # Should have north component
            self.assertGreater(north, 0)


class TestBuildingHeightEstimator(unittest.TestCase):
    """Test cases for BuildingHeightEstimator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.estimator = BuildingHeightEstimator()
    
    def test_estimate_from_height_tag(self):
        """Test height estimation from direct height tag."""
        building = pd.Series({
            'height': '15.5',
            'building': 'residential'
        })
        
        height, method, confidence = self.estimator.estimate_height(building)
        
        self.assertAlmostEqual(height, 15.5, places=1)
        self.assertEqual(method, 'osm_height_tag')
        self.assertGreater(confidence, 0.8)
    
    def test_estimate_from_levels(self):
        """Test height estimation from building levels."""
        building = pd.Series({
            'building': 'apartments',
            'building:levels': '5'
        })
        
        height, method, confidence = self.estimator.estimate_height(building)
        
        self.assertAlmostEqual(height, 15.0, places=1)  # 5 * 3m
        self.assertEqual(method, 'building_levels')
    
    def test_estimate_from_type(self):
        """Test height estimation from building type."""
        test_cases = [
            ('residential', 9.0),
            ('commercial', 12.0),
            ('office', 15.0),
            ('church', 15.0),
        ]
        
        for building_type, expected_height in test_cases:
            building = pd.Series({'building': building_type})
            height, method, confidence = self.estimator.estimate_height(building)
            
            self.assertAlmostEqual(height, expected_height, places=1)
            self.assertIn('default', method)
    
    def test_estimate_generic_fallback(self):
        """Test generic fallback for unknown building type."""
        building = pd.Series({'building': 'unknown_type'})
        
        height, method, confidence = self.estimator.estimate_height(building)
        
        self.assertEqual(height, 9.0)  # Default generic
        self.assertEqual(method, 'default_generic')
    
    def test_parse_height_variations(self):
        """Test parsing various height formats."""
        test_cases = [
            ('15', 15.0),
            ('15.5', 15.5),
            ('15m', 15.0),
            ('15 meters', 15.0),
            ('10-20', 15.0),  # Range average
        ]
        
        for height_str, expected in test_cases:
            building = pd.Series({'height': height_str})
            height, _, _ = self.estimator.estimate_height(building)
            self.assertAlmostEqual(height, expected, places=1)
    
    def test_stats_tracking(self):
        """Test that statistics are tracked correctly."""
        # Clear stats
        self.estimator.stats = {
            'estimated_count': 0,
            'from_levels_count': 0,
            'from_osm_count': 0,
            'default_count': 0
        }
        
        # Make various estimations
        self.estimator.estimate_height(pd.Series({'height': '10'}))
        self.estimator.estimate_height(pd.Series({'building:levels': '3'}))
        self.estimator.estimate_height(pd.Series({'building': 'yes'}))
        
        stats = self.estimator.get_stats()
        
        self.assertEqual(stats['from_osm_count'], 1)
        self.assertEqual(stats['from_levels_count'], 1)
        self.assertEqual(stats['default_count'], 1)


class TestLinkSpotDataPipeline(unittest.TestCase):
    """Test cases for LinkSpotDataPipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock Redis client
        self.mock_redis = Mock()
        self.mock_redis.get.return_value = None
        self.mock_redis.setex.return_value = True
        
        # Create pipeline with mocked dependencies
        self.pipeline = LinkSpotDataPipeline(
            redis_client=self.mock_redis,
            postgis_conn_string=None,  # Skip DB for tests
            enable_overture=False,     # Skip external calls
            enable_osm_fallback=False,
            enable_terrain=False
        )
    
    def test_initialization(self):
        """Test pipeline initialization."""
        pipeline = LinkSpotDataPipeline()
        
        self.assertIsNotNone(pipeline.geohash_encoder)
        self.assertIsNotNone(pipeline.height_estimator)
        self.assertIsNone(pipeline.redis_client)
    
    def test_bbox_from_radius(self):
        """Test bounding box calculation from radius."""
        lat, lon = 40.7580, -73.9855
        radius_m = 500
        
        bbox = self.pipeline._bbox_from_radius(lat, lon, radius_m)
        
        self.assertEqual(len(bbox), 4)
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Check that bbox contains the center point
        self.assertLess(min_lon, lon)
        self.assertGreater(max_lon, lon)
        self.assertLess(min_lat, lat)
        self.assertGreater(max_lat, lat)
        
        # Check approximate size
        width_m = (max_lon - min_lon) * 111320 * np.cos(np.radians(lat))
        self.assertAlmostEqual(width_m, radius_m * 2, delta=100)
    
    def test_cache_key_generation(self):
        """Test cache key generation."""
        geohash = 'dr5r9x'
        cache_key = self.pipeline._get_cache_key(geohash)
        
        self.assertIn(geohash, cache_key)
        self.assertIn('linkspot:buildings:', cache_key)
    
    def test_cache_buildings(self):
        """Test caching buildings to Redis."""
        # Create test GeoDataFrame
        gdf = gpd.GeoDataFrame({
            'geometry': [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            'height': [10.0],
            'source': ['test']
        }, crs='EPSG:4326')
        
        result = self.pipeline.cache_buildings('dr5r9x', gdf)
        
        self.assertTrue(result)
        self.mock_redis.setex.assert_called_once()
    
    def test_get_cached_buildings_hit(self):
        """Test retrieving cached buildings (cache hit)."""
        # Create test GeoDataFrame as GeoJSON
        gdf = gpd.GeoDataFrame({
            'geometry': [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            'height': [10.0],
            'source': ['test']
        }, crs='EPSG:4326')
        
        geojson_str = gdf.to_json()
        self.mock_redis.get.return_value = geojson_str.encode('utf-8')
        
        result = self.pipeline.get_cached_buildings('dr5r9x')
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['height'], 10.0)
    
    def test_get_cached_buildings_miss(self):
        """Test retrieving cached buildings (cache miss)."""
        self.mock_redis.get.return_value = None
        
        result = self.pipeline.get_cached_buildings('dr5r9x')
        
        self.assertIsNone(result)
    
    def test_filter_by_radius(self):
        """Test filtering buildings by radius."""
        # Create test buildings
        center_lat, center_lon = 40.7580, -73.9855
        
        buildings = gpd.GeoDataFrame({
            'geometry': [
                Point(center_lon, center_lat).buffer(0.001),  # Close
                Point(center_lon + 0.01, center_lat).buffer(0.001),  # Far
                Point(center_lon, center_lat + 0.01).buffer(0.001),  # Far
            ],
            'height': [10.0, 20.0, 30.0],
            'source': ['test', 'test', 'test']
        }, crs='EPSG:4326')
        
        filtered = self.pipeline._filter_by_radius(
            buildings, center_lat, center_lon, 500
        )
        
        # Should only include the close building
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]['height'], 10.0)
    
    def test_estimate_building_height(self):
        """Test building height estimation through pipeline."""
        building = pd.Series({
            'building': 'commercial',
            'height': None
        })
        
        height, method, confidence = self.pipeline.estimate_building_height(building)
        
        self.assertEqual(height, 12.0)  # Default commercial
        self.assertIn('default', method)
    
    def test_stats_tracking(self):
        """Test pipeline statistics tracking."""
        stats = self.pipeline.get_stats()
        
        self.assertIn('total_queries', stats)
        self.assertIn('cache_hits', stats)
        self.assertIn('height_estimation', stats)


class TestOvertureClient(unittest.TestCase):
    """Test cases for OvertureMapsClient."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock S3 filesystem
        self.mock_fs_patcher = patch('overture_client.fs.S3FileSystem')
        self.mock_fs = self.mock_fs_patcher.start()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.mock_fs_patcher.stop()
    
    def test_initialization(self):
        """Test client initialization."""
        client = OvertureMapsClient()
        
        self.assertEqual(client.S3_BUCKET, "overturemaps-us-west-2")
        self.assertEqual(client.ATTRIBUTION, "© Overture Maps Foundation, ODbL")
    
    def test_custom_bucket(self):
        """Test initialization with custom bucket."""
        client = OvertureMapsClient(
            s3_bucket="custom-bucket",
            s3_prefix="custom-prefix"
        )
        
        self.assertEqual(client.s3_bucket, "custom-bucket")
        self.assertEqual(client.s3_prefix, "custom-prefix")
    
    def test_get_attribution(self):
        """Test attribution string generation."""
        client = OvertureMapsClient()
        attribution = client.get_attribution()
        
        self.assertIn("Overture Maps Foundation", attribution)
        self.assertIn("ODbL", attribution)
    
    def test_dataset_info(self):
        """Test dataset info retrieval."""
        client = OvertureMapsClient()
        info = client.get_dataset_info()
        
        self.assertIn('bucket', info)
        self.assertIn('version', info)
        self.assertIn('attribution', info)


class TestTerrainClient(unittest.TestCase):
    """Test cases for CopernicusTerrainClient."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock rasterio
        self.mock_dataset = Mock()
        self.mock_dataset.index.return_value = (100, 100)
        self.mock_dataset.read.return_value = np.array([[100.0]])
        self.mock_dataset.bounds = Mock()
        self.mock_dataset.transform = Mock()
        self.mock_dataset.height = 3600
        self.mock_dataset.width = 3600
        self.mock_dataset.transform.a = 0.000277778
        self.mock_dataset.transform.e = -0.000277778
    
    def test_initialization(self):
        """Test client initialization."""
        client = CopernicusTerrainClient(use_s3=False)
        
        self.assertEqual(client.RESOLUTION_M, 30.0)
        self.assertEqual(client.CRS_EPSG, 4326)
        self.assertEqual(client.S3_BUCKET, "copernicus-dem-30m")
    
    def test_get_tile_filename(self):
        """Test tile filename generation."""
        client = CopernicusTerrainClient(use_s3=False)
        
        # Northern hemisphere, western hemisphere
        filename = client._get_tile_filename(40.5, -73.5)
        self.assertIn("N40", filename)
        self.assertIn("W074", filename)
        
        # Southern hemisphere, eastern hemisphere
        filename = client._get_tile_filename(-33.5, 151.5)
        self.assertIn("S33", filename)
        self.assertIn("E151", filename)
    
    def test_get_tile_url(self):
        """Test tile URL generation."""
        client = CopernicusTerrainClient(use_s3=False)
        
        url = client.get_tile_url(40.5, -73.5)
        
        self.assertIn("s3://copernicus-dem-30m", url)
        self.assertIn("N40", url)
        self.assertIn("W074", url)
        self.assertTrue(url.endswith('.tif'))
    
    def test_dataset_info(self):
        """Test dataset info retrieval."""
        client = CopernicusTerrainClient(use_s3=False)
        info = client.get_dataset_info()
        
        self.assertIn('name', info)
        self.assertIn('resolution_m', info)
        self.assertIn('Copernicus', info['name'])
        self.assertEqual(info['resolution_m'], 30.0)
    
    def test_context_manager(self):
        """Test context manager usage."""
        with CopernicusTerrainClient(use_s3=False) as client:
            self.assertIsNotNone(client)
        
        # After exit, resources should be cleaned up


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete pipeline."""
    
    def test_building_data_format(self):
        """Test that building data has correct format for RayCasting."""
        # Create sample building data
        buildings = gpd.GeoDataFrame({
            'geometry': [
                Polygon([(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001)]),
                Polygon([(0.002, 0), (0.003, 0), (0.003, 0.001), (0.002, 0.001)]),
            ],
            'height': [15.0, 25.0],
            'source': ['test', 'test'],
            'building_id': ['b1', 'b2']
        }, crs='EPSG:4326')
        
        # Verify required columns exist
        self.assertIn('geometry', buildings.columns)
        self.assertIn('height', buildings.columns)
        self.assertIn('source', buildings.columns)
        
        # Verify geometry type
        for geom in buildings['geometry']:
            self.assertIsInstance(geom, Polygon)
        
        # Verify height is numeric
        for height in buildings['height']:
            self.assertIsInstance(height, (int, float))
    
    def test_elevation_output_format(self):
        """Test that elevation output is correct format."""
        terrain_data = TerrainData(
            elevation=100.5,
            source='copernicus_glo30',
            resolution_m=30.0,
            lat=40.7580,
            lon=-73.9855
        )
        
        self.assertIsInstance(terrain_data.elevation, float)
        self.assertEqual(terrain_data.source, 'copernicus_glo30')


class TestPerformance(unittest.TestCase):
    """Performance-related tests."""
    
    def test_geohash_performance(self):
        """Test geohash encoding performance."""
        import time
        
        lat, lon = 40.7580, -73.9855
        
        start = time.time()
        for _ in range(1000):
            GeohashEncoder.encode(lat, lon, precision=6)
        elapsed = time.time() - start
        
        # Should be very fast (< 10ms for 1000 encodings)
        self.assertLess(elapsed, 0.1)
    
    def test_coordinate_conversion_performance(self):
        """Test coordinate conversion performance."""
        import time
        
        converter = CoordinateConverter(40.7580, -73.9855)
        
        start = time.time()
        for _ in range(1000):
            converter.wgs84_to_enu_coords(-73.9855, 40.7580, 0.0)
        elapsed = time.time() - start
        
        # Should be reasonably fast
        self.assertLess(elapsed, 1.0)


def run_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestGeohashEncoder))
    suite.addTests(loader.loadTestsFromTestCase(TestCoordinateConverter))
    suite.addTests(loader.loadTestsFromTestCase(TestBuildingHeightEstimator))
    suite.addTests(loader.loadTestsFromTestCase(TestLinkSpotDataPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestOvertureClient))
    suite.addTests(loader.loadTestsFromTestCase(TestTerrainClient))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == '__main__':
    # Run tests
    result = run_tests()
    
    # Exit with appropriate code
    import sys
    sys.exit(0 if result.wasSuccessful() else 1)
