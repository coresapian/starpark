"""API endpoint tests for LinkSpot backend."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Lightweight stubs so tests can run without optional infra deps installed.
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

from dependencies import (
    get_amenity_service,
    get_data_pipeline,
    get_db,
    get_obstruction_engine,
    get_osrm_client,
    get_redis,
    get_satellite_engine,
)
from models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HeatmapRequest,
    RoutePlanRequest,
    Zone,
)
from routers import analysis, health, route, satellites


class _MockRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str):
        return self._data.get(key)

    async def setex(self, key: str, _ttl: int, value: str):
        self._data[key] = value

    async def ping(self):
        return True


class _MockDB:
    async def fetchval(self, _query: str):
        return 1


class _MockSatelliteEngine:
    async def get_visible_satellites(self, **_kwargs):
        return [
            {
                "satellite_id": "STARLINK-1001",
                "norad_id": 1001,
                "azimuth": 45.0,
                "elevation": 38.5,
                "range_km": 550.0,
                "velocity_kms": 7.8,
                "constellation": "Starlink",
                "is_visible": True,
                "name": "STARLINK TEST A",
            },
            {
                "satellite_id": "STARLINK-1002",
                "norad_id": 1002,
                "azimuth": 120.0,
                "elevation": 29.0,
                "range_km": 560.0,
                "velocity_kms": 7.7,
                "constellation": "Starlink",
                "is_visible": True,
                "name": "STARLINK TEST B",
            },
        ]

    async def get_constellations(self):
        return [
            {
                "name": "Starlink",
                "operator": "SpaceX",
                "total_satellites": 2,
                "active_satellites": 2,
                "orbital_planes": 1,
                "altitude_km": 550.1,
                "inclination_deg": 53.2,
            }
        ]


class _MockDataPipeline:
    initialized = True

    async def fetch_buildings(self, **_kwargs):
        return (
            [
                {
                    "lat": 40.7130,
                    "lon": -74.0059,
                    "height": 25.0,
                    "ground_elevation": 0.0,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-74.0061, 40.7129],
                            [-74.0058, 40.7129],
                            [-74.0058, 40.7131],
                            [-74.0061, 40.7131],
                            [-74.0061, 40.7129],
                        ]],
                    },
                }
            ],
            "overture_maps",
        )

    async def fetch_terrain(self, **kwargs):
        return [{"lat": kwargs["lat"], "lon": kwargs["lon"], "elevation": 12.3, "source": "copernicus_glo30"}]


class _MockObstructionEngine:
    sector_width = 2.0
    n_sectors = 180

    def analyze_position(self, **_kwargs):
        return {
            "n_clear": 1,
            "n_total": 2,
            "obstruction_pct": 50.0,
            "blocked_azimuths": [120.0],
            "satellite_details": [
                {
                    "satellite_id": "STARLINK-1001",
                    "name": "STARLINK TEST A",
                    "azimuth": 45.0,
                    "elevation": 38.5,
                    "range_km": 550.0,
                    "is_visible": True,
                    "is_obstructed": False,
                },
                {
                    "satellite_id": "STARLINK-1002",
                    "name": "STARLINK TEST B",
                    "azimuth": 120.0,
                    "elevation": 29.0,
                    "range_km": 560.0,
                    "is_visible": True,
                    "is_obstructed": True,
                },
            ],
            "obstruction_profile": [
                {"azimuth": 121.0, "elevation": 30.0},
            ],
        }


class _MockOSRMClient:
    def get_route(self, origin, destination, profile="driving"):
        _ = profile
        return {
            "geometry": [
                origin,
                ((origin[0] + destination[0]) / 2.0, (origin[1] + destination[1]) / 2.0),
                destination,
            ],
            "distance_m": 20000.0,
            "duration_s": 1200.0,
        }

    def sample_route_points(self, geometry, interval_m=500.0):
        _ = interval_m
        return [
            {"lat": geometry[0][0], "lon": geometry[0][1], "distance_along_m": 0.0},
            {"lat": geometry[1][0], "lon": geometry[1][1], "distance_along_m": 10000.0},
            {"lat": geometry[2][0], "lon": geometry[2][1], "distance_along_m": 20000.0},
        ]


class _MockAmenityService:
    def geocode_address(self, address: str):
        if "denver" in address.lower():
            return 39.7392, -104.9903
        if "boulder" in address.lower():
            return 40.0150, -105.2705
        return 39.9000, -105.1000

    def query_amenities_along_route(self, geometry, buffer_m=500.0):
        _ = buffer_m
        return [
            {
                "lat": geometry[1][0],
                "lon": geometry[1][1],
                "type": "parking",
                "name": "Midpoint Rest Area",
                "parking": True,
                "restroom": True,
                "fuel": False,
                "food": False,
            }
        ]


def _build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(analysis.router)
    app.include_router(satellites.router)
    app.include_router(route.router)
    app.include_router(health.router)

    redis = _MockRedis()
    db = _MockDB()
    sat = _MockSatelliteEngine()
    pipeline = _MockDataPipeline()
    obstruction = _MockObstructionEngine()
    osrm = _MockOSRMClient()
    amenity = _MockAmenityService()

    async def override_redis():
        return redis

    async def override_db():
        return db

    async def override_satellite_engine():
        return sat

    async def override_data_pipeline():
        return pipeline

    async def override_obstruction_engine():
        return obstruction

    async def override_osrm_client():
        return osrm

    async def override_amenity_service():
        return amenity

    app.dependency_overrides[get_redis] = override_redis
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_satellite_engine] = override_satellite_engine
    app.dependency_overrides[get_data_pipeline] = override_data_pipeline
    app.dependency_overrides[get_obstruction_engine] = override_obstruction_engine
    app.dependency_overrides[get_osrm_client] = override_osrm_client
    app.dependency_overrides[get_amenity_service] = override_amenity_service

    return TestClient(app)


class TestHealthEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _build_test_client()

    def test_health_check(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    def test_detailed_health_check(self):
        response = self.client.get("/api/v1/health/detailed")
        self.assertEqual(response.status_code, 200)
        self.assertIn("components", response.json())


class TestAnalysisEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _build_test_client()

    def test_analyze_valid_request(self):
        response = self.client.post(
            "/api/v1/analyze",
            json={"lat": 40.7128, "lon": -74.0060, "elevation": 10.0},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(data["zone"], {"excellent", "good", "fair", "poor", "blocked"})
        self.assertIn("data_quality", data)
        self.assertEqual(data["blocked_azimuths"], [120.0])
        self.assertEqual(data["visibility"]["total_satellites"], 2)

    def test_analyze_returns_data_quality(self):
        response = self.client.post(
            "/api/v1/analyze",
            json={"lat": 40.7128, "lon": -74.0060},
        )
        self.assertEqual(response.status_code, 200)
        dq = response.json()["data_quality"]
        self.assertIn(dq["buildings"], ("full", "partial", "none"))
        self.assertIn(dq["terrain"], ("full", "none"))
        self.assertIn(dq["satellites"], ("live", "cached", "stale"))
        self.assertIsInstance(dq["sources"], list)
        self.assertIsInstance(dq["warnings"], list)

    def test_heatmap_valid_request(self):
        response = self.client.post(
            "/api/v1/heatmap",
            json={"lat": 40.7128, "lon": -74.0060, "radius_m": 100, "spacing_m": 50},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("grid", data)
        self.assertIn("buildings", data)
        self.assertIn("center", data)
        self.assertIn("data_quality", data)

    def test_analyze_invalid_latitude(self):
        response = self.client.post(
            "/api/v1/analyze",
            json={"lat": 100.0, "lon": -74.0060},
        )
        self.assertEqual(response.status_code, 422)


class TestSatelliteEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _build_test_client()

    def test_get_visible_satellites(self):
        response = self.client.get(
            "/api/v1/satellites",
            params={"lat": 40.7128, "lon": -74.0060},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)

    def test_constellation_metadata_not_hardcoded(self):
        response = self.client.get("/api/v1/satellites/constellation")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data["constellations"]), 1)
        for constellation in data["constellations"]:
            self.assertIsNotNone(constellation["name"])
            self.assertGreater(constellation["total_satellites"], 0)
            self.assertIsNotNone(constellation.get("altitude_km"))
            self.assertGreater(constellation.get("altitude_km", 0), 0)


class TestRoutePlanningEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = _build_test_client()

    def test_route_plan_with_coordinates(self):
        response = self.client.post(
            "/api/v1/route/plan",
            json={
                "origin": {"lat": 39.7392, "lon": -104.9903},
                "destination": {"lat": 40.0150, "lon": -105.2705},
                "sample_interval_m": 5000,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("route_geojson", data)
        self.assertIn("waypoints", data)
        self.assertIn("dead_zones", data)
        self.assertIn("mission_summary", data)
        self.assertIn("signal_forecast", data)
        self.assertIn("data_quality", data)

    def test_route_plan_with_addresses(self):
        response = self.client.post(
            "/api/v1/route/plan",
            json={
                "origin": {"address": "Denver, CO"},
                "destination": {"address": "Boulder, CO"},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(data["mission_summary"]["total_distance_m"], 0)
        self.assertIsInstance(data["waypoints"], list)


class TestSchemaValidation(unittest.TestCase):
    def test_analyze_request_schema(self):
        request = AnalyzeRequest(lat=40.7128, lon=-74.0060, elevation=10.0)
        self.assertEqual(request.lat, 40.7128)

    def test_analyze_response_schema(self):
        response = AnalyzeResponse(
            zone=Zone.GOOD,
            n_clear=42,
            n_total=50,
            obstruction_pct=16.0,
            blocked_azimuths=[30.0, 60.0],
            timestamp=datetime.now(timezone.utc),
            lat=40.7128,
            lon=-74.0060,
        )
        self.assertEqual(response.zone, Zone.GOOD)

    def test_heatmap_request_schema(self):
        request = HeatmapRequest(
            lat=40.7128,
            lon=-74.0060,
            radius_m=1000,
            spacing_m=100,
        )
        self.assertEqual(request.spacing_m, 100)

    def test_route_plan_request_schema(self):
        req = RoutePlanRequest(
            origin={"lat": 39.7392, "lon": -104.9903},
            destination={"address": "Boulder, CO"},
            sample_interval_m=750.0,
        )
        self.assertEqual(req.sample_interval_m, 750.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
