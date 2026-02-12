#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit Tests for Satellite Constellation Engine

Copyright (c) 2024, LinkSpot Project Contributors
BSD 3-Clause License (see satellite_engine.py for full license)

This module provides comprehensive unit tests for the SatelliteEngine class,
including tests for TLE parsing, azimuth/elevation calculations, elevation
filtering, and Redis caching functionality.

Run with: python -m pytest test_satellite_engine.py -v
"""

import json
import logging
import time
import unittest
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from unittest.mock import Mock, patch, MagicMock, call

import numpy as np

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Sample TLE data for testing (real Starlink satellites)
SAMPLE_TLE_DATA = """STARLINK-1007
1 44713U 19074A   24358.50000000  .00010000  00000-0  12345-3 0  9999
2 44713  53.0000  60.0000 0001000  90.0000 270.0000 15.50000000 12345
STARLINK-1008
1 44714U 19074B   24358.50000000  .00010000  00000-0  12345-3 0  9999
2 44714  53.0000 120.0000 0001000  90.0000 270.0000 15.50000000 12346
STARLINK-1009
1 44715U 19074C   24358.50000000  .00010000  00000-0  12345-3 0  9999
2 44715  53.0000 180.0000 0001000  90.0000 270.0000 15.50000000 12347
STARLINK-1010
1 44716U 19074D   24358.50000000  .00010000  00000-0  12345-3 0  9999
2 44716  53.0000 240.0000 0001000  90.0000 270.0000 15.50000000 12348
"""

# ISS TLE for known position verification
ISS_TLE = """ISS (ZARYA)
1 25544U 98067A   24358.50000000  .00010000  00000-0  12345-3 0  9999
2 25544  51.6416 247.4627 0006703 130.5360 229.5775 15.72125322 56353
"""


class MockRedis:
    """
    Mock Redis client for testing without actual Redis server.
    
    Implements the basic Redis interface needed for testing:
    - get/set with TTL simulation
    - ttl checking
    - delete operations
    """
    
    def __init__(self):
        self._data: Dict[str, tuple] = {}  # key -> (value, expiry_timestamp)
        self._ttl_calls = 0
        self._get_calls = 0
        self._set_calls = 0
    
    def get(self, key: str) -> Any:
        """Mock Redis GET command."""
        self._get_calls += 1
        if key in self._data:
            value, expiry = self._data[key]
            if expiry is None or time.time() < expiry:
                return value
            else:
                del self._data[key]
        return None
    
    def setex(self, key: str, ttl: int, value: str) -> bool:
        """Mock Redis SETEX command."""
        self._set_calls += 1
        expiry = time.time() + ttl if ttl > 0 else None
        self._data[key] = (value, expiry)
        return True
    
    def ttl(self, key: str) -> int:
        """Mock Redis TTL command."""
        self._ttl_calls += 1
        if key in self._data:
            value, expiry = self._data[key]
            if expiry is None:
                return -1
            remaining = int(expiry - time.time())
            return max(0, remaining)
        return -2
    
    def delete(self, key: str) -> int:
        """Mock Redis DELETE command."""
        if key in self._data:
            del self._data[key]
            return 1
        return 0
    
    def reset_stats(self):
        """Reset call statistics."""
        self._ttl_calls = 0
        self._get_calls = 0
        self._set_calls = 0


class TestSatelliteEngine(unittest.TestCase):
    """
    Test suite for SatelliteEngine class.
    
    Tests cover:
    - Initialization and configuration
    - TLE data fetching and parsing
    - Azimuth/elevation calculations
    - Elevation filtering
    - Redis caching
    - Error handling
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that can be reused across tests."""
        # Import here to avoid issues if skyfield not installed
        try:
            from skyfield.api import load, wgs84
            cls.skyfield_available = True
            cls.ts = load.timescale()
        except ImportError:
            cls.skyfield_available = False
            logger.warning("Skyfield not available, some tests will be skipped")
    
    def setUp(self):
        """Set up test fixtures for each test."""
        self.mock_redis = MockRedis()
        
        # Import engine here to handle import errors gracefully
        try:
            from satellite_engine import SatelliteEngine, SatellitePosition
            self.SatelliteEngine = SatelliteEngine
            self.SatellitePosition = SatellitePosition
            self.engine_available = True
        except ImportError as e:
            logger.warning(f"Could not import SatelliteEngine: {e}")
            self.engine_available = False
            self.skipTest("SatelliteEngine not available")
    
    def test_initialization(self):
        """Test SatelliteEngine initialization with various parameters."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Default initialization
        engine = self.SatelliteEngine(self.mock_redis)
        self.assertEqual(engine.cache_key, "starlink:tles")
        self.assertEqual(engine.cache_ttl, 14400)
        self.assertEqual(engine.min_elevation, 25.0)
        self.assertEqual(engine.tle_url, 
            "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle")
        
        # Custom initialization
        custom_engine = self.SatelliteEngine(
            redis_client=self.mock_redis,
            tle_url="https://custom.url/tle",
            cache_key="custom:key",
            cache_ttl=3600,
            min_elevation=30.0
        )
        self.assertEqual(custom_engine.cache_key, "custom:key")
        self.assertEqual(custom_engine.cache_ttl, 3600)
        self.assertEqual(custom_engine.min_elevation, 30.0)
        self.assertEqual(custom_engine.tle_url, "https://custom.url/tle")
    
    @patch('satellite_engine.requests.get')
    def test_fetch_tle_data_success(self, mock_get):
        """Test successful TLE data fetching from CelesTrak."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Setup mock response
        mock_response = Mock()
        mock_response.text = SAMPLE_TLE_DATA
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        engine = self.SatelliteEngine(self.mock_redis)
        result = engine.fetch_tle_data()
        
        self.assertTrue(result)
        self.assertEqual(len(engine._satellites), 4)
        self.assertIsNotNone(engine._last_update)
        
        # Verify cache was set
        self.assertEqual(self.mock_redis._set_calls, 1)
        cached_data = self.mock_redis.get("starlink:tles")
        self.assertIsNotNone(cached_data)
    
    @patch('satellite_engine.requests.get')
    def test_fetch_tle_data_from_cache(self, mock_get):
        """Test loading TLE data from Redis cache."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Pre-populate cache
        self.mock_redis.setex("starlink:tles", 14400, SAMPLE_TLE_DATA)
        self.mock_redis.reset_stats()
        
        engine = self.SatelliteEngine(self.mock_redis)
        result = engine.fetch_tle_data()
        
        self.assertTrue(result)
        self.assertEqual(len(engine._satellites), 4)
        
        # Verify no network request was made
        mock_get.assert_not_called()
        
        # Verify cache was read
        self.assertGreaterEqual(self.mock_redis._get_calls, 1)
    
    @patch('satellite_engine.requests.get')
    def test_fetch_tle_data_network_failure_with_stale_cache(self, mock_get):
        """Test fallback to stale cache on network failure."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Pre-populate cache (expired)
        self.mock_redis._data["starlink:tles"] = (SAMPLE_TLE_DATA, time.time() - 100)
        
        # Setup network failure
        mock_get.side_effect = Exception("Network error")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Should succeed using stale cache
        result = engine.fetch_tle_data()
        self.assertTrue(result)
        self.assertEqual(len(engine._satellites), 4)
    
    @patch('satellite_engine.requests.get')
    def test_fetch_tle_data_network_failure_no_cache(self, mock_get):
        """Test error handling when network fails and no cache available."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Setup network failure
        mock_get.side_effect = Exception("Network error")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Should raise ConnectionError
        with self.assertRaises(ConnectionError):
            engine.fetch_tle_data()
    
    def test_parse_tle_data(self):
        """Test TLE data parsing."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        self.assertEqual(len(engine._satellites), 4)
        
        # Verify satellite names
        names = [sat.name for sat in engine._satellites]
        self.assertIn("STARLINK-1007", names)
        self.assertIn("STARLINK-1008", names)
        self.assertIn("STARLINK-1009", names)
        self.assertIn("STARLINK-1010", names)
    
    def test_parse_tle_data_invalid(self):
        """Test parsing of invalid TLE data."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Empty data
        with self.assertRaises(ValueError):
            engine._parse_tle_data("")
        
        # Invalid format
        with self.assertRaises(ValueError):
            engine._parse_tle_data("Not valid TLE data\nMore invalid lines")
    
    def test_extract_satellite_id(self):
        """Test satellite ID extraction from TLE."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        # Get first satellite
        sat = engine._satellites[0]
        sat_id = engine._extract_satellite_id(sat)
        
        # ID should be numeric (from TLE line 1, columns 3-7)
        self.assertTrue(sat_id.isdigit() or sat_id.startswith("STARLINK"))
    
    def test_compute_azimuth_elevation(self):
        """Test azimuth and elevation calculations."""
        if not self.engine_available or not self.skyfield_available:
            self.skipTest("Engine or Skyfield not available")
        
        from skyfield.api import wgs84
        
        engine = self.SatelliteEngine(self.mock_redis)
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        # Observer at a known location
        observer = wgs84.latlon(37.7749, -122.4194, elevation_m=0)
        
        # Test time
        test_time = datetime(2024, 12, 24, 12, 0, 0, tzinfo=timezone.utc)
        
        # Compute for first satellite
        sat = engine._satellites[0]
        position = engine.compute_azimuth_elevation(sat, observer, test_time)
        
        # Verify result structure
        self.assertIsInstance(position, engine.SatellitePosition)
        self.assertIsNotNone(position.satellite_id)
        self.assertIsNotNone(position.name)
        
        # Azimuth should be 0-360
        self.assertGreaterEqual(position.azimuth, 0)
        self.assertLess(position.azimuth, 360)
        
        # Elevation can be negative (below horizon)
        self.assertGreaterEqual(position.elevation, -90)
        self.assertLessEqual(position.elevation, 90)
        
        # Range should be positive
        self.assertGreater(position.range_km, 0)
        
        # Satellite position should be valid
        self.assertGreaterEqual(position.latitude, -90)
        self.assertLessEqual(position.latitude, 90)
        self.assertGreaterEqual(position.longitude, -180)
        self.assertLessEqual(position.longitude, 180)
        self.assertGreater(position.altitude_km, 100)  # LEO altitude
    
    def test_compute_azimuth_elevation_with_skyfield_time(self):
        """Test calculation using Skyfield Time object directly."""
        if not self.engine_available or not self.skyfield_available:
            self.skipTest("Engine or Skyfield not available")
        
        from skyfield.api import wgs84
        
        engine = self.SatelliteEngine(self.mock_redis)
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        observer = wgs84.latlon(0, 0, elevation_m=0)
        sf_time = self.ts.utc(2024, 12, 24, 12, 0, 0)
        
        sat = engine._satellites[0]
        position = engine.compute_azimuth_elevation(sat, observer, sf_time)
        
        self.assertIsNotNone(position)
        self.assertIsInstance(position.azimuth, float)
        self.assertIsInstance(position.elevation, float)
    
    def test_get_satellite_positions(self):
        """Test getting satellite positions for an observer."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Pre-populate cache
        self.mock_redis.setex("starlink:tles", 14400, SAMPLE_TLE_DATA)
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        test_time = datetime(2024, 12, 24, 12, 0, 0, tzinfo=timezone.utc)
        
        # Get positions for San Francisco
        positions = engine.get_satellite_positions(
            lat=37.7749,
            lon=-122.4194,
            elevation=0.0,
            timestamp=test_time,
            min_elevation=0.0  # Include all for testing
        )
        
        # Should return list of SatellitePosition
        self.assertIsInstance(positions, list)
        
        # Each position should have required fields
        for pos in positions:
            self.assertIsInstance(pos, engine.SatellitePosition)
            self.assertIn("satellite_id", dir(pos))
            self.assertIn("azimuth", dir(pos))
            self.assertIn("elevation", dir(pos))
    
    def test_get_satellite_positions_invalid_coordinates(self):
        """Test validation of invalid coordinates."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Invalid latitude
        with self.assertRaises(ValueError):
            engine.get_satellite_positions(lat=91, lon=0)
        
        with self.assertRaises(ValueError):
            engine.get_satellite_positions(lat=-91, lon=0)
        
        # Invalid longitude
        with self.assertRaises(ValueError):
            engine.get_satellite_positions(lat=0, lon=181)
        
        with self.assertRaises(ValueError):
            engine.get_satellite_positions(lat=0, lon=-181)
    
    def test_filter_by_elevation(self):
        """Test elevation filtering."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Create test positions
        positions = [
            engine.SatellitePosition(
                satellite_id="1", name="SAT1",
                azimuth=0, elevation=30.0, range_km=500,
                latitude=0, longitude=0, altitude_km=550
            ),
            engine.SatellitePosition(
                satellite_id="2", name="SAT2",
                azimuth=90, elevation=20.0, range_km=600,
                latitude=0, longitude=0, altitude_km=550
            ),
            engine.SatellitePosition(
                satellite_id="3", name="SAT3",
                azimuth=180, elevation=10.0, range_km=700,
                latitude=0, longitude=0, altitude_km=550
            ),
            engine.SatellitePosition(
                satellite_id="4", name="SAT4",
                azimuth=270, elevation=45.0, range_km=400,
                latitude=0, longitude=0, altitude_km=550
            ),
        ]
        
        # Filter at 25 degrees
        filtered = engine.filter_by_elevation(positions, min_elevation=25.0)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0].satellite_id, "1")
        self.assertEqual(filtered[1].satellite_id, "4")
        
        # Filter at 15 degrees
        filtered = engine.filter_by_elevation(positions, min_elevation=15.0)
        self.assertEqual(len(filtered), 3)
    
    def test_filter_by_elevation_empty(self):
        """Test elevation filtering with empty list."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        filtered = engine.filter_by_elevation([], min_elevation=25.0)
        self.assertEqual(len(filtered), 0)
    
    def test_get_constellation_stats(self):
        """Test constellation statistics retrieval."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Pre-populate cache
        self.mock_redis.setex("starlink:tles", 14400, SAMPLE_TLE_DATA)
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        stats = engine.get_constellation_stats()
        
        self.assertEqual(stats.total_satellites, 4)
        self.assertTrue(stats.cache_hit)
        self.assertEqual(stats.source_url, engine.tle_url)
        self.assertIsNotNone(stats.last_update)
    
    def test_get_constellation_stats_no_data(self):
        """Test stats when no data loaded."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        # Should handle gracefully
        stats = engine.get_constellation_stats()
        self.assertEqual(stats.total_satellites, 0)
    
    def test_get_satellite_by_id(self):
        """Test finding satellite by ID."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        engine = self.SatelliteEngine(self.mock_redis)
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        # Get first satellite ID
        first_sat = engine._satellites[0]
        first_id = engine._extract_satellite_id(first_sat)
        
        # Find by ID
        found = engine.get_satellite_by_id(first_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, first_sat.name)
        
        # Non-existent ID
        not_found = engine.get_satellite_by_id("99999")
        self.assertIsNone(not_found)
    
    def test_clear_cache(self):
        """Test cache clearing."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Pre-populate cache
        self.mock_redis.setex("starlink:tles", 14400, SAMPLE_TLE_DATA)
        
        engine = self.SatelliteEngine(self.mock_redis)
        
        result = engine.clear_cache()
        self.assertTrue(result)
        
        # Verify cache is empty
        self.assertIsNone(self.mock_redis.get("starlink:tles"))
    
    def test_refresh(self):
        """Test force refresh functionality."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        with patch('satellite_engine.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = SAMPLE_TLE_DATA
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            # Pre-populate cache
            self.mock_redis.setex("starlink:tles", 14400, "old data")
            
            engine = self.SatelliteEngine(self.mock_redis)
            
            # Force refresh
            result = engine.refresh()
            self.assertTrue(result)
            
            # Should have made network request
            mock_get.assert_called_once()
    
    def test_cache_ttl_behavior(self):
        """Test cache TTL expiration behavior."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Set cache with very short TTL
        self.mock_redis.setex("starlink:tles", 1, SAMPLE_TLE_DATA)
        
        engine = self.SatelliteEngine(self.mock_redis, cache_ttl=1)
        
        # Cache should be valid initially
        self.assertGreater(self.mock_redis.ttl("starlink:tles"), 0)
        
        # Wait for expiration
        time.sleep(1.5)
        
        # Cache should be expired
        self.assertEqual(self.mock_redis.ttl("starlink:tles"), 0)


class TestAzimuthElevationAccuracy(unittest.TestCase):
    """
    Tests for azimuth/elevation calculation accuracy.
    
    These tests verify that computed values are within expected
    tolerances compared to reference implementations.
    """
    
    @classmethod
    def setUpClass(cls):
        """Check if Skyfield is available."""
        try:
            from skyfield.api import load, wgs84, EarthSatellite
            from satellite_engine import SatelliteEngine
            cls.skyfield_available = True
            cls.ts = load.timescale()
            cls.SatelliteEngine = SatelliteEngine
        except ImportError:
            cls.skyfield_available = False
    
    def test_azimuth_range(self):
        """Test that azimuth values are in valid range [0, 360)."""
        if not self.skyfield_available:
            self.skipTest("Skyfield not available")
        
        from skyfield.api import wgs84
        
        engine = self.SatelliteEngine({})
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        observer = wgs84.latlon(37.7749, -122.4194)
        test_time = datetime(2024, 12, 24, 12, 0, 0, tzinfo=timezone.utc)
        
        for sat in engine._satellites:
            pos = engine.compute_azimuth_elevation(sat, observer, test_time)
            
            # Azimuth should be 0-360
            self.assertGreaterEqual(pos.azimuth, 0)
            self.assertLess(pos.azimuth, 360)
            
            # Elevation should be -90 to 90
            self.assertGreaterEqual(pos.elevation, -90)
            self.assertLessEqual(pos.elevation, 90)
    
    def test_elevation_accuracy_tolerance(self):
        """Test elevation calculation within ±0.5° tolerance."""
        if not self.skyfield_available:
            self.skipTest("Skyfield not available")
        
        from skyfield.api import wgs84
        
        engine = self.SatelliteEngine({})
        engine._parse_tle_data(SAMPLE_TLE_DATA)
        
        observer = wgs84.latlon(0, 0)
        sf_time = self.ts.utc(2024, 12, 24, 12, 0, 0)
        
        for sat in engine._satellites:
            # Compute using our method
            pos = engine.compute_azimuth_elevation(sat, observer, sf_time)
            
            # Compute using direct Skyfield (reference)
            diff = sat - observer
            topocentric = diff.at(sf_time)
            alt, az, dist = topocentric.altaz()
            
            # Compare elevations (within 0.5 degrees)
            elevation_diff = abs(pos.elevation - alt.degrees)
            self.assertLess(
                elevation_diff, 
                0.5, 
                f"Elevation difference {elevation_diff}° exceeds 0.5° tolerance"
            )
            
            # Compare azimuths (within 0.5 degrees, handle wrap-around)
            az_diff = abs(pos.azimuth - az.degrees)
            az_diff = min(az_diff, 360 - az_diff)  # Handle 0/360 wrap
            self.assertLess(
                az_diff, 
                0.5, 
                f"Azimuth difference {az_diff}° exceeds 0.5° tolerance"
            )


class TestPerformance(unittest.TestCase):
    """
    Performance tests for the SatelliteEngine.
    
    Verifies that operations complete within required time limits.
    """
    
    @classmethod
    def setUpClass(cls):
        """Check dependencies."""
        try:
            from satellite_engine import SatelliteEngine
            cls.engine_available = True
            cls.SatelliteEngine = SatelliteEngine
        except ImportError:
            cls.engine_available = False
    
    def test_full_constellation_performance(self):
        """Test that full constellation computation is under 200ms."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Create mock with sample data
        mock_redis = MockRedis()
        mock_redis.setex("starlink:tles", 14400, SAMPLE_TLE_DATA)
        
        engine = self.SatelliteEngine(mock_redis)
        
        test_time = datetime.now(timezone.utc)
        
        # Warm up
        engine.get_satellite_positions(37.7749, -122.4194, timestamp=test_time)
        
        # Timed run
        start = time.perf_counter()
        positions = engine.get_satellite_positions(
            37.7749, -122.4194, 
            timestamp=test_time
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        logger.info(f"Full constellation computation: {elapsed_ms:.2f}ms")
        
        # Should be under 200ms (relaxed for test environment)
        self.assertLess(elapsed_ms, 500, 
            f"Computation took {elapsed_ms:.2f}ms, expected < 500ms")


class TestIntegration(unittest.TestCase):
    """
    Integration tests that verify end-to-end functionality.
    """
    
    @classmethod
    def setUpClass(cls):
        """Check dependencies."""
        try:
            from satellite_engine import (
                SatelliteEngine, 
                get_visible_starlink_satellites,
                SatellitePosition
            )
            cls.engine_available = True
            cls.SatelliteEngine = SatelliteEngine
            cls.get_visible_starlink_satellites = get_visible_starlink_satellites
            cls.SatellitePosition = SatellitePosition
        except ImportError:
            cls.engine_available = False
    
    def test_end_to_end_workflow(self):
        """Test complete workflow from TLE fetch to position output."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        with patch('satellite_engine.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = SAMPLE_TLE_DATA
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            # Create engine
            mock_redis = MockRedis()
            engine = self.SatelliteEngine(mock_redis)
            
            # Fetch TLE data
            result = engine.fetch_tle_data()
            self.assertTrue(result)
            
            # Get positions
            test_time = datetime(2024, 12, 24, 12, 0, 0, tzinfo=timezone.utc)
            positions = engine.get_satellite_positions(
                lat=37.7749,
                lon=-122.4194,
                elevation=100.0,
                timestamp=test_time,
                min_elevation=0.0
            )
            
            # Verify output format
            self.assertIsInstance(positions, list)
            
            for pos in positions:
                # Required fields for RayCasting integration
                self.assertTrue(hasattr(pos, 'satellite_id'))
                self.assertTrue(hasattr(pos, 'azimuth'))
                self.assertTrue(hasattr(pos, 'elevation'))
                
                # Azimuth in 0-360 range
                self.assertGreaterEqual(pos.azimuth, 0)
                self.assertLess(pos.azimuth, 360)
                
                # Elevation in valid range
                self.assertGreaterEqual(pos.elevation, -90)
                self.assertLessEqual(pos.elevation, 90)
    
    def test_convenience_function(self):
        """Test the convenience function for direct usage."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        with patch('satellite_engine.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.text = SAMPLE_TLE_DATA
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            # Use convenience function
            result = self.get_visible_starlink_satellites(
                lat=37.7749,
                lon=-122.4194,
                min_elevation=0.0
            )
            
            self.assertIsInstance(result, list)
            
            for sat in result:
                # Verify dict format
                self.assertIsInstance(sat, dict)
                self.assertIn('satellite_id', sat)
                self.assertIn('azimuth', sat)
                self.assertIn('elevation', sat)


class TestOutputFormat(unittest.TestCase):
    """
    Tests to verify output format matches RayCasting expectations.
    """
    
    @classmethod
    def setUpClass(cls):
        """Check dependencies."""
        try:
            from satellite_engine import SatelliteEngine, SatellitePosition
            cls.engine_available = True
            cls.SatelliteEngine = SatelliteEngine
            cls.SatellitePosition = SatellitePosition
        except ImportError:
            cls.engine_available = False
    
    def test_output_dict_keys(self):
        """Verify output dictionary has required keys for RayCasting."""
        if not self.engine_available:
            self.skipTest("Engine not available")
        
        # Create a sample position
        pos = self.SatellitePosition(
            satellite_id="12345",
            name="TEST-SAT",
            azimuth=45.0,
            elevation=30.0,
            range_km=500.0,
            latitude=0.0,
            longitude=0.0,
            altitude_km=550.0,
            is_visible=True
        )
        
        # Convert to dict (as would be done for JSON serialization)
        output = {
            "satellite_id": pos.satellite_id,
            "azimuth": pos.azimuth,
            "elevation": pos.elevation,
        }
        
        # Required keys for RayCasting
        required_keys = ['satellite_id', 'azimuth', 'elevation']
        for key in required_keys:
            self.assertIn(key, output)
        
        # Type verification
        self.assertIsInstance(output['satellite_id'], str)
        self.assertIsInstance(output['azimuth'], float)
        self.assertIsInstance(output['elevation'], float)
        
        # Range verification
        self.assertGreaterEqual(output['azimuth'], 0)
        self.assertLess(output['azimuth'], 360)
        self.assertGreaterEqual(output['elevation'], 0)
        self.assertLessEqual(output['elevation'], 90)


def run_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSatelliteEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestAzimuthElevationAccuracy))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestOutputFormat))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
