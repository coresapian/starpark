# -*- coding: utf-8 -*-
# Copyright (c) 2024, LinkSpot Project Contributors
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
LinkSpot Database Tests

Comprehensive test suite for database operations including:
- Connection management
- CRUD operations
- Spatial queries
- Cache operations
- Performance benchmarks
"""

import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Generator

import pytest
import pytest_asyncio
from geoalchemy2 import functions as geo_funcs
from shapely.geometry import Polygon
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker, Session

# Import models and connection
from database.models import Base, Building, TerrainTile, TLECache, AnalysisCache
from database.connection import Database
from database.queries import (
    get_buildings_in_radius,
    get_buildings_in_radius_async,
    get_buildings_in_bbox,
    get_cached_analysis,
    cache_analysis_result,
    compute_geohash,
)
from cache.redis_client import RedisCache


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def database_url() -> str:
    """Get database URL from environment or use default."""
    return os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/linkspot_test"
    )


@pytest.fixture(scope="session")
def redis_url() -> str:
    """Get Redis URL from environment or use default."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def db_engine(database_url: str):
    """Create database engine for tests."""
    engine = create_engine(database_url, echo=False)
    
    # Enable PostGIS
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS "uuid-ossp";"))
        conn.commit()
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    yield engine
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create a fresh database session for each test."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    
    # Clear tables before each test
    session.query(Building).delete()
    session.query(TerrainTile).delete()
    session.query(TLECache).delete()
    session.query(AnalysisCache).delete()
    session.commit()
    
    yield session
    
    session.rollback()
    session.close()


@pytest.fixture
async def redis_client(redis_url: str):
    """Create Redis client for tests."""
    cache = RedisCache(redis_url)
    await cache.connect_async()
    
    # Clear test keys
    await cache.delete_pattern_async("test:*")
    await cache.delete_pattern_async("buildings:*")
    await cache.delete_pattern_async("tles:*")
    await cache.delete_pattern_async("analysis:*")
    
    yield cache
    
    # Cleanup
    await cache.delete_pattern_async("test:*")
    await cache.close_async()


# =============================================================================
# Database Connection Tests
# =============================================================================

class TestDatabaseConnection:
    """Test database connection management."""
    
    def test_database_init(self, database_url: str):
        """Test Database class initialization."""
        db = Database(database_url)
        assert db.connection_string == database_url
        assert db.engine is None
        assert db.SessionLocal is None
    
    def test_database_connect(self, database_url: str):
        """Test database connection."""
        db = Database(database_url)
        db.connect()
        
        assert db.engine is not None
        assert db.SessionLocal is not None
        assert db.async_engine is not None
        assert db.AsyncSessionLocal is not None
        
        # Test health check
        assert db.health_check() is True
        
        db.close()
    
    def test_database_context_manager(self, database_url: str):
        """Test session context manager."""
        db = Database(database_url)
        db.connect()
        db.enable_postgis()
        
        with db.get_session() as session:
            result = session.execute(text("SELECT 1"))
            assert result.scalar() == 1
        
        db.close()
    
    @pytest.mark.asyncio
    async def test_database_async_connect(self, database_url: str):
        """Test async database connection."""
        db = Database(database_url)
        db.connect()
        
        async with db.get_async_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
        
        await db.close_async()


# =============================================================================
# Model Tests
# =============================================================================

class TestBuildingModel:
    """Test Building model operations."""
    
    def test_create_building(self, db_session: Session):
        """Test creating a building record."""
        building = Building(
            geometry="SRID=4326;POLYGON((-122.4 37.8, -122.39 37.8, -122.39 37.79, -122.4 37.79, -122.4 37.8))",
            height=50.0,
            source="test",
            source_id="test_001",
            height_source="test_source",
            height_confidence=0.85,
        )
        
        db_session.add(building)
        db_session.commit()
        
        assert building.id is not None
        assert building.height == 50.0
        assert building.source == "test"
        assert building.updated_at is not None
    
    def test_building_to_dict(self, db_session: Session):
        """Test building serialization."""
        building = Building(
            geometry="SRID=4326;POLYGON((-122.4 37.8, -122.39 37.8, -122.39 37.79, -122.4 37.79, -122.4 37.8))",
            height=50.0,
            source="test",
            source_id="test_002",
        )
        
        db_session.add(building)
        db_session.commit()
        
        data = building.to_dict()
        assert "id" in data
        assert data["height"] == 50.0
        assert data["source"] == "test"
    
    def test_building_unique_constraint(self, db_session: Session):
        """Test unique constraint on source/source_id."""
        building1 = Building(
            geometry="SRID=4326;POLYGON((-122.4 37.8, -122.39 37.8, -122.39 37.79, -122.4 37.79, -122.4 37.8))",
            height=50.0,
            source="test",
            source_id="unique_test",
        )
        
        db_session.add(building1)
        db_session.commit()
        
        # Attempt to add duplicate
        building2 = Building(
            geometry="SRID=4326;POLYGON((-122.41 37.81, -122.40 37.81, -122.40 37.80, -122.41 37.80, -122.41 37.81))",
            height=60.0,
            source="test",
            source_id="unique_test",
        )
        
        db_session.add(building2)
        
        with pytest.raises(Exception):
            db_session.commit()
        
        db_session.rollback()


class TestTerrainTileModel:
    """Test TerrainTile model operations."""
    
    def test_create_terrain_tile(self, db_session: Session):
        """Test creating a terrain tile record."""
        tile = TerrainTile(
            bbox="SRID=4326;POLYGON((-123 37, -122 37, -122 38, -123 38, -123 37))",
            s3_path="s3://test-bucket/terrain/test.tif",
            resolution_m=30.0,
        )
        
        db_session.add(tile)
        db_session.commit()
        
        assert tile.id is not None
        assert tile.s3_path == "s3://test-bucket/terrain/test.tif"
        assert tile.resolution_m == 30.0


class TestTLECacheModel:
    """Test TLECache model operations."""
    
    def test_create_tle_cache(self, db_session: Session):
        """Test creating TLE cache entry."""
        tle = TLECache(
            constellation="test_constellation",
            tle_data="TEST TLE DATA\nLINE 1\nLINE 2",
            fetched_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=4),
        )
        
        db_session.add(tle)
        db_session.commit()
        
        assert tle.id is not None
        assert tle.constellation == "test_constellation"


class TestAnalysisCacheModel:
    """Test AnalysisCache model operations."""
    
    def test_create_analysis_cache(self, db_session: Session):
        """Test creating analysis cache entry."""
        cache = AnalysisCache(
            geohash="dqcjqc",
            lat=37.7946,
            lon=-122.4020,
            result_json={"score": 0.85, "data": [1, 2, 3]},
            computed_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        
        db_session.add(cache)
        db_session.commit()
        
        assert cache.id is not None
        assert cache.geohash == "dqcjqc"
        assert cache.access_count == 0


# =============================================================================
# Spatial Query Tests
# =============================================================================

class TestSpatialQueries:
    """Test spatial query functions."""
    
    @pytest.fixture(autouse=True)
    def setup_buildings(self, db_session: Session):
        """Create test buildings for spatial queries."""
        buildings = [
            Building(
                geometry=f"SRID=4326;POLYGON((-122.401{ i%10 } 37.791{ i%10 }, -122.401{ (i+1)%10 } 37.791{ i%10 }, -122.401{ (i+1)%10 } 37.791{ (i+1)%10 }, -122.401{ i%10 } 37.791{ (i+1)%10 }, -122.401{ i%10 } 37.791{ i%10 }))",
                height=float(20 + i * 10),
                source="test_spatial",
                source_id=f"spatial_{i}",
            )
            for i in range(10)
        ]
        
        db_session.add_all(buildings)
        db_session.commit()
    
    def test_get_buildings_in_radius(self, db_session: Session):
        """Test radius-based building query."""
        # Query around Financial District
        buildings = get_buildings_in_radius(
            db_session,
            lat=37.7910,
            lon=-122.4010,
            radius_m=1000.0,
        )
        
        assert isinstance(buildings, list)
        # Should find our test buildings
        assert len(buildings) > 0
    
    def test_get_buildings_in_radius_with_height_filter(self, db_session: Session):
        """Test radius query with height filter."""
        buildings = get_buildings_in_radius(
            db_session,
            lat=37.7910,
            lon=-122.4010,
            radius_m=2000.0,
            min_height=50.0,
        )
        
        assert isinstance(buildings, list)
        for b in buildings:
            assert b["height"] >= 50.0
    
    def test_get_buildings_in_bbox(self, db_session: Session):
        """Test bounding box building query."""
        buildings = get_buildings_in_bbox(
            db_session,
            min_lat=37.7900,
            min_lon=-122.4020,
            max_lat=37.7920,
            max_lon=-122.4000,
        )
        
        assert isinstance(buildings, list)
    
    @pytest.mark.asyncio
    async def test_get_buildings_in_radius_async(self, database_url: str):
        """Test async radius query."""
        db = Database(database_url)
        db.connect()
        
        async with db.get_async_session() as session:
            buildings = await get_buildings_in_radius_async(
                session,
                lat=37.7910,
                lon=-122.4010,
                radius_m=1000.0,
            )
            assert isinstance(buildings, list)
        
        await db.close_async()


# =============================================================================
# Cache Tests
# =============================================================================

class TestRedisCache:
    """Test Redis cache operations."""
    
    @pytest.mark.asyncio
    async def test_redis_connect(self, redis_url: str):
        """Test Redis connection."""
        cache = RedisCache(redis_url)
        await cache.connect_async()
        
        assert cache.health_check_async is not None
        
        await cache.close_async()
    
    @pytest.mark.asyncio
    async def test_set_get_string(self, redis_client: RedisCache):
        """Test basic string operations."""
        key = "test:string"
        value = "hello world"
        
        await redis_client.set_async(key, value, ttl_seconds=60)
        result = await redis_client.get_async(key)
        
        assert result == value
    
    @pytest.mark.asyncio
    async def test_set_get_json(self, redis_client: RedisCache):
        """Test JSON operations."""
        key = "test:json"
        value = {"name": "test", "count": 42, "items": [1, 2, 3]}
        
        await redis_client.set_json_async(key, value, ttl_seconds=60)
        result = await redis_client.get_json_async(key)
        
        assert result == value
    
    @pytest.mark.asyncio
    async def test_buildings_cache(self, redis_client: RedisCache):
        """Test building cache operations."""
        geohash = "dqcjqc"
        buildings_data = [
            {"id": "1", "height": 50.0, "geometry": "{}"},
            {"id": "2", "height": 75.0, "geometry": "{}"},
        ]
        
        await redis_client.set_buildings_async(geohash, buildings_data)
        result = await redis_client.get_buildings_async(geohash)
        
        assert result is not None
        assert result["geohash"] == geohash
        assert len(result["buildings"]) == 2
    
    @pytest.mark.asyncio
    async def test_tles_cache(self, redis_client: RedisCache):
        """Test TLE cache operations."""
        constellation = "starlink"
        tle_data = "TEST TLE\nLINE 1\nLINE 2\nLINE 3"
        
        await redis_client.set_tles_async(constellation, tle_data)
        result = await redis_client.get_tles_async(constellation)
        
        assert result == tle_data
    
    @pytest.mark.asyncio
    async def test_analysis_cache(self, redis_client: RedisCache):
        """Test analysis cache operations."""
        geohash = "dqcjqc"
        analysis_result = {
            "score": 0.85,
            "obstructions": [],
            "satellites": 15,
        }
        
        await redis_client.set_analysis_async(geohash, analysis_result)
        result = await redis_client.get_analysis_async(geohash)
        
        assert result is not None
        assert result["result"]["score"] == 0.85
    
    @pytest.mark.asyncio
    async def test_ttl(self, redis_client: RedisCache):
        """Test TTL functionality."""
        key = "test:ttl"
        value = "test"
        
        await redis_client.set_async(key, value, ttl_seconds=3600)
        ttl = await redis_client.ttl_async(key)
        
        assert ttl > 0
        assert ttl <= 3600
    
    @pytest.mark.asyncio
    async def test_delete(self, redis_client: RedisCache):
        """Test delete operation."""
        key = "test:delete"
        
        await redis_client.set_async(key, "value", ttl_seconds=60)
        assert await redis_client.exists_async(key) is True
        
        await redis_client.delete_async(key)
        assert await redis_client.exists_async(key) is False
    
    @pytest.mark.asyncio
    async def test_geohash_utils(self, redis_client: RedisCache):
        """Test geohash utility functions."""
        # Test compute_geohash
        geohash = RedisCache.compute_geohash(37.7749, -122.4194, precision=6)
        assert len(geohash) == 6
        
        # Test geohash_to_bbox
        bbox = RedisCache.geohash_to_bbox(geohash)
        assert len(bbox) == 4
        
        # Test get_neighbor_geohashes
        neighbors = RedisCache.get_neighbor_geohashes(geohash)
        assert "n" in neighbors
        assert "s" in neighbors
        assert "e" in neighbors
        assert "w" in neighbors


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Test performance requirements."""
    
    @pytest.mark.slow
    def test_radius_query_performance(self, db_session: Session):
        """Test that radius queries meet performance targets."""
        # Create test data
        buildings = [
            Building(
                geometry=f"SRID=4326;POLYGON((-122.{400+i//100:03d} 37.{790+i%100:03d}, -122.{400+i//100:03d} 37.{791+i%100:03d}, -122.{401+i//100:03d} 37.{791+i%100:03d}, -122.{401+i//100:03d} 37.{790+i%100:03d}, -122.{400+i//100:03d} 37.{790+i%100:03d}))",
                height=float(10 + (i % 50)),
                source="perf_test",
                source_id=f"perf_{i}",
            )
            for i in range(100)
        ]
        
        db_session.add_all(buildings)
        db_session.commit()
        
        # Warm up
        get_buildings_in_radius(db_session, 37.795, -122.405, 500.0)
        
        # Measure cold query (target: < 3 seconds)
        start = time.time()
        result = get_buildings_in_radius(db_session, 37.795, -122.405, 500.0)
        cold_time = time.time() - start
        
        # Measure hot query (target: < 500ms)
        start = time.time()
        result = get_buildings_in_radius(db_session, 37.795, -122.405, 500.0)
        hot_time = time.time() - start
        
        # Log performance
        print(f"\nPerformance Results:")
        print(f"  Cold query: {cold_time*1000:.2f}ms (target: < 3000ms)")
        print(f"  Hot query: {hot_time*1000:.2f}ms (target: < 500ms)")
        
        # Assert performance targets
        assert cold_time < 3.0, f"Cold query too slow: {cold_time}s"
        assert hot_time < 0.5, f"Hot query too slow: {hot_time}s"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for database + cache."""
    
    @pytest.mark.asyncio
    async def test_cache_fallback_to_database(
        self,
        database_url: str,
        redis_url: str,
    ):
        """Test cache miss falls back to database."""
        # Setup database
        db = Database(database_url)
        db.connect()
        
        # Setup Redis
        cache = RedisCache(redis_url)
        await cache.connect_async()
        
        # Create test building in database
        with db.get_session() as session:
            building = Building(
                geometry="SRID=4326;POLYGON((-122.4 37.8, -122.39 37.8, -122.39 37.79, -122.4 37.79, -122.4 37.8))",
                height=100.0,
                source="integration_test",
                source_id="int_001",
            )
            session.add(building)
            session.commit()
        
        # Try cache first (miss)
        geohash = "dqcjqc"
        cached = await cache.get_buildings_async(geohash)
        assert cached is None  # Cache miss
        
        # Query database
        with db.get_session() as session:
            buildings = get_buildings_in_radius(session, 37.795, -122.395, 1000.0)
            assert len(buildings) > 0
        
        # Populate cache
        await cache.set_buildings_async(geohash, buildings)
        
        # Verify cache hit
        cached = await cache.get_buildings_async(geohash)
        assert cached is not None
        
        # Cleanup
        await cache.close_async()
        db.close()


# =============================================================================
# Utility Tests
# =============================================================================

def test_compute_geohash():
    """Test geohash computation."""
    # San Francisco coordinates
    geohash = compute_geohash(37.7749, -122.4194, precision=6)
    assert len(geohash) == 6
    assert geohash == "dqcjqc"


def test_geohash_precision():
    """Test different geohash precisions."""
    lat, lon = 37.7749, -122.4194
    
    precisions = [4, 5, 6, 7, 8]
    for p in precisions:
        geohash = compute_geohash(lat, lon, precision=p)
        assert len(geohash) == p


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
