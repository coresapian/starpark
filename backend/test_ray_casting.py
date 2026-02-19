"""Ray-casting and geometry unit tests aligned to current backend adapters."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime

import numpy as np

# Lightweight stubs so importing dependencies does not require optional infra deps.
if "redis.asyncio" not in sys.modules:
    redis_mod = types.ModuleType("redis")
    redis_async_mod = types.ModuleType("redis.asyncio")
    class _StubRedis:
        async def ping(self):
            return True
    redis_async_mod.Redis = _StubRedis
    redis_async_mod.RedisError = Exception
    redis_async_mod.from_url = lambda *args, **kwargs: _StubRedis()
    redis_mod.asyncio = redis_async_mod
    sys.modules["redis"] = redis_mod
    sys.modules["redis.asyncio"] = redis_async_mod

if "asyncpg" not in sys.modules:
    asyncpg_mod = types.ModuleType("asyncpg")
    asyncpg_mod.Connection = object
    asyncpg_mod.Pool = object
    asyncpg_mod.PostgresError = Exception
    asyncpg_mod.create_pool = lambda *args, **kwargs: None
    sys.modules["asyncpg"] = asyncpg_mod

from dependencies import _ObstructionEngineAdapter
from enu_utils import azimuth_to_sector_index, calculate_azimuth, wgs84_to_enu
from ray_casting_engine import AnalysisResult, Satellite, Zone


class TestENUUtilities(unittest.TestCase):
    def test_wgs84_to_enu_origin(self):
        lat, lon, elev = 40.7128, -74.0060, 10.0
        e, n, u = wgs84_to_enu(lat, lon, elev, lat, lon, elev)
        self.assertAlmostEqual(e, 0.0, places=6)
        self.assertAlmostEqual(n, 0.0, places=6)
        self.assertAlmostEqual(u, 0.0, places=6)

    def test_azimuth_cardinals(self):
        self.assertAlmostEqual(calculate_azimuth(0, 0, 0, 100), 0.0, places=6)
        self.assertAlmostEqual(calculate_azimuth(0, 0, 100, 0), 90.0, places=6)
        self.assertAlmostEqual(calculate_azimuth(0, 0, 0, -100), 180.0, places=6)
        self.assertAlmostEqual(calculate_azimuth(0, 0, -100, 0), 270.0, places=6)

    def test_azimuth_sector_index_wraps(self):
        self.assertEqual(azimuth_to_sector_index(0.0, 2.0), 0)
        self.assertEqual(azimuth_to_sector_index(359.0, 2.0), 179)
        self.assertEqual(azimuth_to_sector_index(360.0, 2.0), 0)


class TestRayCastingModels(unittest.TestCase):
    def test_zone_values(self):
        self.assertEqual(Zone.GREEN.value, "green")
        self.assertEqual(Zone.AMBER.value, "amber")
        self.assertEqual(Zone.DEAD.value, "dead")

    def test_analysis_result_to_dict(self):
        result = AnalysisResult(
            zone=Zone.GREEN,
            n_clear=4,
            n_total=5,
            obstruction_pct=20.0,
            blocked_azimuths=[30.123, 60.789],
            obstruction_profile=np.array([-90.0] * 180),
            timestamp=datetime(2024, 1, 1),
            lat=40.7128,
            lon=-74.0060,
            elevation=10.0,
            processing_time_ms=12.345,
        )
        payload = result.to_dict()
        self.assertEqual(payload["zone"], "green")
        self.assertEqual(payload["n_clear"], 4)
        self.assertEqual(payload["blocked_azimuths"], [30.1, 60.8])

    def test_satellite_dataclass(self):
        sat = Satellite(prn="G01", azimuth=45.0, elevation=30.0)
        self.assertEqual(sat.prn, "G01")
        self.assertEqual(sat.system, "GPS")


class TestObstructionEngineAdapter(unittest.TestCase):
    def setUp(self):
        self.engine = _ObstructionEngineAdapter()
        self.lat = 40.7128
        self.lon = -74.0060

    def test_no_visible_satellites(self):
        result = self.engine.analyze_position(
            lat=self.lat,
            lon=self.lon,
            elevation=0.0,
            buildings=[],
            terrain=[],
            satellites=[],
        )
        self.assertEqual(result["n_total"], 0)
        self.assertEqual(result["n_clear"], 0)
        self.assertEqual(result["obstruction_pct"], 100.0)

    def test_clear_line_of_sight_without_buildings(self):
        satellites = [
            {
                "satellite_id": "S1",
                "azimuth": 45.0,
                "elevation": 35.0,
                "is_visible": True,
            }
        ]
        result = self.engine.analyze_position(
            lat=self.lat,
            lon=self.lon,
            elevation=0.0,
            buildings=[],
            terrain=[],
            satellites=satellites,
        )
        self.assertEqual(result["n_total"], 1)
        self.assertEqual(result["n_clear"], 1)
        self.assertEqual(result["blocked_azimuths"], [])

    def test_building_blocks_satellite(self):
        satellites = [
            {
                "satellite_id": "S2",
                "azimuth": 0.0,
                "elevation": 30.0,
                "is_visible": True,
            }
        ]
        buildings = [
            {
                "lat": self.lat + 0.00045,
                "lon": self.lon,
                "height": 60.0,
                "ground_elevation": 0.0,
            }
        ]
        result = self.engine.analyze_position(
            lat=self.lat,
            lon=self.lon,
            elevation=0.0,
            buildings=buildings,
            terrain=[],
            satellites=satellites,
        )
        self.assertEqual(result["n_total"], 1)
        self.assertEqual(result["n_clear"], 0)
        self.assertEqual(len(result["blocked_azimuths"]), 1)

    def test_satellite_details_and_obstruction_profile(self):
        satellites = [
            {
                "satellite_id": "S1",
                "name": "SAT A",
                "azimuth": 180.0,
                "elevation": 40.0,
                "range_km": 550.0,
                "is_visible": True,
            }
        ]
        result = self.engine.analyze_position(
            lat=self.lat,
            lon=self.lon,
            elevation=0.0,
            buildings=[],
            terrain=[],
            satellites=satellites,
        )
        self.assertEqual(len(result["satellite_details"]), 1)
        self.assertIn("satellite_id", result["satellite_details"][0])
        self.assertIsInstance(result["obstruction_profile"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
