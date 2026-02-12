# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Health check endpoints for monitoring and status reporting.

"""Health check API endpoints for LinkSpot."""

import logging
import time
from datetime import datetime, timezone
from typing import Any

import aioredis
import asyncpg
from fastapi import APIRouter, Depends, Request

from config import settings
from dependencies import (
    get_data_pipeline,
    get_db,
    get_db_pool,
    get_obstruction_engine,
    get_redis,
    get_redis_pool,
    get_satellite_engine,
)
from models.schemas import (
    ComponentHealth,
    ComponentStatus,
    DetailedHealthResponse,
    HealthResponse,
    ProblemDetail,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/v1/health", tags=["Health"])

# Track application start time for uptime calculation
_app_start_time: float = time.time()


# ============================================================================
# Helper Functions
# ============================================================================

async def _check_redis_health(redis: aioredis.Redis) -> ComponentHealth:
    """Check Redis health status.
    
    Args:
        redis: Redis connection.
        
    Returns:
        ComponentHealth: Redis health status.
    """
    start_time = time.time()
    try:
        await redis.ping()
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="redis",
            status=ComponentStatus.HEALTHY,
            latency_ms=round(latency_ms, 2),
            last_check=datetime.now(timezone.utc),
        )
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="redis",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(latency_ms, 2),
            message=str(e),
            last_check=datetime.now(timezone.utc),
        )


async def _check_database_health(db: asyncpg.Connection) -> ComponentHealth:
    """Check database health status.
    
    Args:
        db: Database connection.
        
    Returns:
        ComponentHealth: Database health status.
    """
    start_time = time.time()
    try:
        result = await db.fetchval("SELECT 1")
        if result == 1:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="database",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                last_check=datetime.now(timezone.utc),
            )
        else:
            raise Exception("Unexpected query result")
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="database",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(latency_ms, 2),
            message=str(e),
            last_check=datetime.now(timezone.utc),
        )


async def _check_satellite_engine_health(
    satellite_engine: Any,
) -> ComponentHealth:
    """Check satellite engine health status.
    
    Args:
        satellite_engine: Satellite engine instance.
        
    Returns:
        ComponentHealth: Satellite engine health status.
    """
    start_time = time.time()
    try:
        # Try to get constellations as a simple health check
        constellations = await satellite_engine.get_constellations()
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="satellite_engine",
            status=ComponentStatus.HEALTHY,
            latency_ms=round(latency_ms, 2),
            message=f"{len(constellations)} constellations loaded",
            last_check=datetime.now(timezone.utc),
        )
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="satellite_engine",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(latency_ms, 2),
            message=str(e),
            last_check=datetime.now(timezone.utc),
        )


async def _check_data_pipeline_health(data_pipeline: Any) -> ComponentHealth:
    """Check data pipeline health status.
    
    Args:
        data_pipeline: Data pipeline instance.
        
    Returns:
        ComponentHealth: Data pipeline health status.
    """
    start_time = time.time()
    try:
        # Check if pipeline is initialized
        if hasattr(data_pipeline, 'initialized') and data_pipeline.initialized:
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="data_pipeline",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                last_check=datetime.now(timezone.utc),
            )
        else:
            # Try to initialize
            if hasattr(data_pipeline, 'initialize'):
                await data_pipeline.initialize()
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="data_pipeline",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                last_check=datetime.now(timezone.utc),
            )
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="data_pipeline",
            status=ComponentStatus.DEGRADED,
            latency_ms=round(latency_ms, 2),
            message=str(e),
            last_check=datetime.now(timezone.utc),
        )


def _check_obstruction_engine_health(obstruction_engine: Any) -> ComponentHealth:
    """Check obstruction engine health status.
    
    Args:
        obstruction_engine: Obstruction engine instance.
        
    Returns:
        ComponentHealth: Obstruction engine health status.
    """
    start_time = time.time()
    try:
        # Check if engine has required attributes
        if hasattr(obstruction_engine, 'resolution'):
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="obstruction_engine",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                message=f"Resolution: {obstruction_engine.resolution}",
                last_check=datetime.now(timezone.utc),
            )
        else:
            raise Exception("Engine not properly initialized")
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="obstruction_engine",
            status=ComponentStatus.UNHEALTHY,
            latency_ms=round(latency_ms, 2),
            message=str(e),
            last_check=datetime.now(timezone.utc),
        )


def _calculate_overall_status(components: list[ComponentHealth]) -> ComponentStatus:
    """Calculate overall health status from component statuses.
    
    Args:
        components: List of component health statuses.
        
    Returns:
        ComponentStatus: Overall health status.
    """
    statuses = [c.status for c in components]
    
    if any(s == ComponentStatus.UNHEALTHY for s in statuses):
        return ComponentStatus.UNHEALTHY
    elif any(s == ComponentStatus.DEGRADED for s in statuses):
        return ComponentStatus.DEGRADED
    elif all(s == ComponentStatus.HEALTHY for s in statuses):
        return ComponentStatus.HEALTHY
    
    return ComponentStatus.UNKNOWN


# ============================================================================
# Basic Health Check Endpoint
# ============================================================================

@router.get(
    "",
    response_model=HealthResponse,
    responses={
        200: {"description": "Service is healthy"},
        503: {"model": ProblemDetail, "description": "Service is unhealthy"},
    },
    summary="Basic health check",
    description="""
    Returns basic health status of the API service.
    
    This endpoint is suitable for load balancer health checks.
    Returns 200 if the service is running, 503 if unhealthy.
    
    **Response:**
    - `status`: Overall service status (healthy/unhealthy)
    - `version`: API version
    - `timestamp`: Health check timestamp
    - `uptime_seconds`: Service uptime in seconds
    """,
)
async def health_check(request: Request) -> HealthResponse:
    """Basic health check endpoint.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        HealthResponse: Basic health status.
    """
    uptime = time.time() - _app_start_time
    
    return HealthResponse(
        status=ComponentStatus.HEALTHY,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        uptime_seconds=round(uptime, 2),
    )


# ============================================================================
# Detailed Health Check Endpoint
# ============================================================================

@router.get(
    "/detailed",
    response_model=DetailedHealthResponse,
    responses={
        200: {"description": "Detailed health status retrieved"},
        503: {"model": ProblemDetail, "description": "Service is unhealthy"},
    },
    summary="Detailed health check",
    description="""
    Returns detailed health status including all component checks.
    
    Components checked:
    - Database (PostgreSQL)
    - Cache (Redis)
    - Satellite Engine
    - Data Pipeline
    - Obstruction Engine
    
    Each component includes:
    - Status (healthy/degraded/unhealthy)
    - Response latency
    - Status message (if applicable)
    - Last check timestamp
    
    **Overall Status Logic:**
    - `healthy`: All components healthy
    - `degraded`: Some components degraded, none unhealthy
    - `unhealthy`: Any component unhealthy
    """,
)
async def detailed_health_check(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
    data_pipeline: Any = Depends(get_data_pipeline),
    obstruction_engine: Any = Depends(get_obstruction_engine),
) -> DetailedHealthResponse:
    """Detailed health check endpoint.
    
    Args:
        request: FastAPI request object.
        redis: Redis connection.
        db: Database connection.
        satellite_engine: Satellite engine instance.
        data_pipeline: Data pipeline instance.
        obstruction_engine: Obstruction engine instance.
        
    Returns:
        DetailedHealthResponse: Detailed health status.
    """
    logger.info("Performing detailed health check")
    
    # Check all components
    components = []
    
    # Check Redis
    try:
        redis_health = await _check_redis_health(redis)
        components.append(redis_health)
    except Exception as e:
        components.append(
            ComponentHealth(
                name="redis",
                status=ComponentStatus.UNHEALTHY,
                message=f"Connection error: {str(e)}",
                last_check=datetime.now(timezone.utc),
            )
        )
    
    # Check Database
    try:
        db_health = await _check_database_health(db)
        components.append(db_health)
    except Exception as e:
        components.append(
            ComponentHealth(
                name="database",
                status=ComponentStatus.UNHEALTHY,
                message=f"Connection error: {str(e)}",
                last_check=datetime.now(timezone.utc),
            )
        )
    
    # Check Satellite Engine
    try:
        satellite_health = await _check_satellite_engine_health(satellite_engine)
        components.append(satellite_health)
    except Exception as e:
        components.append(
            ComponentHealth(
                name="satellite_engine",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )
    
    # Check Data Pipeline
    try:
        pipeline_health = await _check_data_pipeline_health(data_pipeline)
        components.append(pipeline_health)
    except Exception as e:
        components.append(
            ComponentHealth(
                name="data_pipeline",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )
    
    # Check Obstruction Engine
    try:
        obstruction_health = _check_obstruction_engine_health(obstruction_engine)
        components.append(obstruction_health)
    except Exception as e:
        components.append(
            ComponentHealth(
                name="obstruction_engine",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )
    
    # Calculate overall status
    overall_status = _calculate_overall_status(components)
    uptime = time.time() - _app_start_time
    
    logger.info(
        f"Health check complete: status={overall_status.value}, "
        f"components={len(components)}"
    )
    
    return DetailedHealthResponse(
        status=overall_status,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        uptime_seconds=round(uptime, 2),
        components=components,
        environment=settings.environment,
    )


# ============================================================================
# Readiness Check Endpoint
# ============================================================================

@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={
        200: {"description": "Service is ready"},
        503: {"model": ProblemDetail, "description": "Service not ready"},
    },
    summary="Readiness check",
    description="""
    Returns readiness status for Kubernetes-style readiness probes.
    
    The service is considered ready when:
    - Database connection is established
    - Redis connection is established
    - Satellite engine is initialized
    
    This endpoint is suitable for Kubernetes readiness probes.
    """,
)
async def readiness_check(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
    db: asyncpg.Connection = Depends(get_db),
    satellite_engine: Any = Depends(get_satellite_engine),
) -> HealthResponse:
    """Readiness check endpoint for Kubernetes probes.
    
    Args:
        request: FastAPI request object.
        redis: Redis connection.
        db: Database connection.
        satellite_engine: Satellite engine instance.
        
    Returns:
        HealthResponse: Readiness status.
        
    Raises:
        HTTPException: If service is not ready.
    """
    from fastapi import HTTPException, status
    
    try:
        # Check Redis
        await redis.ping()
        
        # Check Database
        await db.fetchval("SELECT 1")
        
        # Check Satellite Engine
        await satellite_engine.get_constellations()
        
        uptime = time.time() - _app_start_time
        
        return HealthResponse(
            status=ComponentStatus.HEALTHY,
            version=settings.app_version,
            timestamp=datetime.now(timezone.utc),
            uptime_seconds=round(uptime, 2),
        )
        
    except Exception as e:
        logger.warning(f"Readiness check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready: {str(e)}",
        )


# ============================================================================
# Liveness Check Endpoint
# ============================================================================

@router.get(
    "/live",
    response_model=HealthResponse,
    responses={
        200: {"description": "Service is alive"},
    },
    summary="Liveness check",
    description="""
    Returns liveness status for Kubernetes-style liveness probes.
    
    This endpoint always returns 200 if the service process is running.
    It does not check external dependencies.
    
    This endpoint is suitable for Kubernetes liveness probes.
    """,
)
async def liveness_check(request: Request) -> HealthResponse:
    """Liveness check endpoint for Kubernetes probes.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        HealthResponse: Liveness status.
    """
    uptime = time.time() - _app_start_time
    
    return HealthResponse(
        status=ComponentStatus.HEALTHY,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        uptime_seconds=round(uptime, 2),
    )
