# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# FastAPI dependencies for dependency injection.
# Provides database, cache, and engine connections.

"""FastAPI dependencies for LinkSpot API."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

import redis.asyncio as aioredis
import asyncpg
from fastapi import Depends, HTTPException, Request, status

# Configure logging
logger = logging.getLogger(__name__)

# Singleton instances (initialized on first use)
_redis_pool: Optional[aioredis.Redis] = None
_db_pool: Optional[asyncpg.Pool] = None
_satellite_engine: Optional[Any] = None
_data_pipeline: Optional[Any] = None
_obstruction_engine: Optional[Any] = None

# Import configuration
from config import settings


# ============================================================================
# Redis Dependency
# ============================================================================

async def get_redis_pool() -> aioredis.Redis:
    """Get or create Redis connection pool.
    
    Returns:
        aioredis.Redis: Redis client instance.
        
    Raises:
        HTTPException: If Redis connection fails.
    """
    global _redis_pool
    
    if _redis_pool is None:
        try:
            _redis_pool = aioredis.from_url(
                str(settings.redis_url),
                encoding="utf-8",
                decode_responses=True,
                max_connections=settings.redis_pool_size,
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_connect_timeout,
            )
            # Test connection
            await _redis_pool.ping()
            logger.info("Redis connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache service unavailable"
            )
    
    return _redis_pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency for Redis connection.
    
    Yields:
        aioredis.Redis: Redis client for request scope.
    """
    redis = await get_redis_pool()
    try:
        yield redis
    except Exception as e:
        logger.error(f"Redis operation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache operation failed"
        )


# ============================================================================
# Database Dependency
# ============================================================================

async def get_db_pool() -> asyncpg.Pool:
    """Get or create PostgreSQL connection pool.
    
    Returns:
        asyncpg.Pool: Database connection pool.
        
    Raises:
        HTTPException: If database connection fails.
    """
    global _db_pool
    
    if _db_pool is None:
        try:
            _db_pool = await asyncpg.create_pool(
                str(settings.database_url),
                min_size=5,
                max_size=settings.database_pool_size,
                max_inactive_connection_lifetime=300,
                command_timeout=30,
                server_settings={
                    "application_name": "linkspot_api",
                    "jit": "off",  # Disable JIT for short queries
                },
            )
            # Test connection
            async with _db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service unavailable"
            )
    
    return _db_pool


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """FastAPI dependency for database connection.
    
    Yields:
        asyncpg.Connection: Database connection for request scope.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            yield conn
        except asyncpg.PostgresError as e:
            logger.error(f"Database query failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database query failed"
            )


@asynccontextmanager
async def get_db_transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager for database transactions.
    
    Usage:
        async with get_db_transaction() as conn:
            result = await conn.fetch("SELECT ...")
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# ============================================================================
# Satellite Engine Dependency
# ============================================================================

async def get_satellite_engine() -> Any:
    """Get or initialize satellite engine singleton.
    
    The satellite engine computes satellite positions and visibility.
    
    Returns:
        SatelliteEngine: Initialized satellite engine instance.
        
    Raises:
        HTTPException: If engine initialization fails.
    """
    global _satellite_engine
    
    if _satellite_engine is None:
        # Use mock engine that matches the router interface
        _satellite_engine = _MockSatelliteEngine()
        logger.info("Satellite engine initialized (mock)")
    
    return _satellite_engine


class _MockSatelliteEngine:
    """Mock satellite engine for development/testing."""
    
    def __init__(self):
        self.elevation_mask = 10.0
    
    async def initialize(self):
        """Initialize the mock engine."""
        pass
    
    async def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> list[dict]:
        """Return mock satellite data."""
        return [
            {
                "satellite_id": "STARLINK-MOCK-001",
                "norad_id": 99999,
                "azimuth": 45.0,
                "elevation": 25.0,
                "range_km": 550.0,
                "velocity_kms": 7.8,
                "constellation": "Starlink",
            },
            {
                "satellite_id": "STARLINK-MOCK-002",
                "norad_id": 99998,
                "azimuth": 120.0,
                "elevation": 35.0,
                "range_km": 545.0,
                "velocity_kms": 7.8,
                "constellation": "Starlink",
            },
        ]
    
    async def get_constellations(self) -> list[dict]:
        """Return mock constellation data."""
        return [
            {
                "name": "Starlink",
                "operator": "SpaceX",
                "total_satellites": 5000,
                "active_satellites": 4500,
            }
        ]


# ============================================================================
# Data Pipeline Dependency
# ============================================================================

async def get_data_pipeline() -> Any:
    """Get or initialize data pipeline singleton.
    
    The data pipeline fetches and processes building/terrain data.
    
    Returns:
        DataPipeline: Initialized data pipeline instance.
    """
    global _data_pipeline
    
    if _data_pipeline is None:
        # Use mock pipeline that matches the router interface
        _data_pipeline = _MockDataPipeline()
        logger.info("Data pipeline initialized (mock)")
    
    return _data_pipeline


class _MockDataPipeline:
    """Mock data pipeline for development/testing."""
    
    async def initialize(self):
        """Initialize the mock pipeline."""
        pass
    
    async def fetch_buildings(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> list[dict]:
        """Return mock building data."""
        return []
    
    async def fetch_terrain(
        self,
        lat: float,
        lon: float,
        radius_m: float,
    ) -> list[dict]:
        """Return mock terrain data."""
        return []


# ============================================================================
# Obstruction Engine Dependency
# ============================================================================

async def get_obstruction_engine() -> Any:
    """Get or initialize obstruction engine singleton.
    
    The obstruction engine performs ray casting for visibility analysis.
    
    Returns:
        ObstructionEngine: Initialized obstruction engine instance.
    """
    global _obstruction_engine
    
    if _obstruction_engine is None:
        # Use mock engine that matches the router interface
        _obstruction_engine = _MockObstructionEngine()
        logger.info("Obstruction engine initialized (mock)")
    
    return _obstruction_engine


class _MockObstructionEngine:
    """Mock obstruction engine for development/testing."""
    
    def __init__(self):
        self.resolution = 360
    
    def analyze_position(
        self,
        lat: float,
        lon: float,
        elevation: float,
        buildings: list[dict],
        terrain: list[dict],
        satellites: list[dict],
    ) -> dict:
        """Return mock obstruction analysis."""
        return {
            "n_clear": 40,
            "n_total": 50,
            "obstruction_pct": 20.0,
            "blocked_azimuths": [[30.0, 60.0], [150.0, 180.0]],
        }
    
    def get_zone(self, clear_ratio: float) -> str:
        """Classify coverage zone."""
        if clear_ratio >= 0.9:
            return "excellent"
        elif clear_ratio >= 0.7:
            return "good"
        elif clear_ratio >= 0.4:
            return "fair"
        elif clear_ratio > 0.0:
            return "poor"
        return "blocked"


# ============================================================================
# Request ID Dependency
# ============================================================================

def get_request_id(request: Request) -> str:
    """Extract or generate request ID for tracing.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        str: Request ID for logging and tracing.
    """
    # Check for existing request ID in headers
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        return request_id
    
    # Generate new request ID
    import uuid
    return f"req-{uuid.uuid4().hex[:12]}"


# ============================================================================
# API Key Dependency (optional)
# ============================================================================

async def verify_api_key(request: Request) -> Optional[str]:
    """Verify API key if configured.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        Optional[str]: API key if valid, None if not required.
        
    Raises:
        HTTPException: If API key is invalid.
    """
    if not settings.api_key:
        return None  # API key not required
    
    api_key = request.headers.get(settings.api_key_header)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    
    return api_key


# ============================================================================
# Combined Dependencies
# ============================================================================

async def get_analysis_dependencies(
    redis: aioredis.Redis = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
) -> dict:
    """Get all analysis dependencies in one call.
    
    Returns:
        dict: Dictionary containing all analysis dependencies.
    """
    return {
        "redis": redis,
        "db": db,
        "satellite_engine": satellite_engine,
        "data_pipeline": data_pipeline,
        "obstruction_engine": obstruction_engine,
    }


# ============================================================================
# Cleanup Functions
# ============================================================================

async def close_dependencies() -> None:
    """Close all dependency connections.
    
    Call this during application shutdown.
    """
    global _redis_pool, _db_pool, _satellite_engine, _data_pipeline, _obstruction_engine
    
    # Close Redis
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection pool closed")
    
    # Close database
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
        logger.info("Database connection pool closed")
    
    # Clear engine references
    _satellite_engine = None
    _data_pipeline = None
    _obstruction_engine = None
    logger.info("Engine singletons cleared")


