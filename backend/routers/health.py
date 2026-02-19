# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Health check endpoints for monitoring and status reporting.

"""Health check API endpoints for LinkSpot."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Request

from config import settings
from dependencies import (
    get_data_pipeline,
    get_db_pool,
    get_obstruction_engine,
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
_readiness_cache: dict[str, Any] = {"checked_at": 0.0, "ready": False}


# ============================================================================
# Helper Functions
# ============================================================================

async def _check_redis_health(redis: Any) -> ComponentHealth:
    """Check Redis health status.
    
    Args:
        redis: Redis connection.
        
    Returns:
        ComponentHealth: Redis health status.
    """
    start_time = time.time()
    try:
        ping_result = await redis.ping()
        if ping_result is not True:
            raise RuntimeError("redis_unavailable")
        latency_ms = (time.time() - start_time) * 1000
        return ComponentHealth(
            name="redis",
            status=ComponentStatus.HEALTHY,
            latency_ms=round(latency_ms, 2),
            last_check=datetime.now(timezone.utc),
        )
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        # TODO: Add Redis command-specific probes (info/mem) to detect auth vs connectivity degradations.
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
        # TODO: Capture DB error class (timeout/permission/schema) separately for targeted remediation.
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
        # TODO: Bound constellation probe time since this call can become expensive with full refreshs.
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
            # TODO: Avoid initializing heavy pipeline from health checks; use a lightweight readiness flag instead.
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
        if hasattr(obstruction_engine, 'sector_width'):
            latency_ms = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="obstruction_engine",
                status=ComponentStatus.HEALTHY,
                latency_ms=round(latency_ms, 2),
                message=f"Sector width: {obstruction_engine.sector_width}°, {obstruction_engine.n_sectors} sectors",
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
    # TODO: Add UNKNOWN/MAINTENANCE handling when health checks are partially timed out.
    
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
) -> DetailedHealthResponse:
    """Detailed health check endpoint.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        DetailedHealthResponse: Detailed health status.
    """
    logger.info("Performing detailed health check")
    
    async def _run_probe(name: str, probe_coro: Any) -> ComponentHealth:
        try:
            return await asyncio.wait_for(probe_coro, timeout=settings.health_timeout_seconds)
        except asyncio.TimeoutError:
            return ComponentHealth(
                name=name,
                status=ComponentStatus.DEGRADED,
                message="probe_timeout",
                last_check=datetime.now(timezone.utc),
            )
        except Exception as e:
            return ComponentHealth(
                name=name,
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )

    components: list[ComponentHealth] = []

    try:
        redis = await get_redis_pool()
        components.append(await _run_probe("redis", _check_redis_health(redis)))
    except Exception as e:
        components.append(
            ComponentHealth(
                name="redis",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )

    try:
        db_pool = await get_db_pool()
        async with db_pool.acquire() as db:
            components.append(await _run_probe("database", _check_database_health(db)))
    except Exception as e:
        components.append(
            ComponentHealth(
                name="database",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )

    try:
        satellite_engine = await get_satellite_engine()
        components.append(
            await _run_probe("satellite_engine", _check_satellite_engine_health(satellite_engine))
        )
    except Exception as e:
        components.append(
            ComponentHealth(
                name="satellite_engine",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )

    try:
        data_pipeline = await get_data_pipeline()
        components.append(await _run_probe("data_pipeline", _check_data_pipeline_health(data_pipeline)))
    except Exception as e:
        components.append(
            ComponentHealth(
                name="data_pipeline",
                status=ComponentStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(timezone.utc),
            )
        )

    # Obstruction check is CPU-local and cheap; run inline.
    try:
        obstruction_engine = await get_obstruction_engine()
        components.append(_check_obstruction_engine_health(obstruction_engine))
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
) -> HealthResponse:
    """Readiness check endpoint for Kubernetes probes.
    
    Args:
        request: FastAPI request object.
        
    Returns:
        HealthResponse: Readiness status.
        
    Raises:
        HTTPException: If service is not ready.
    """
    from fastapi import HTTPException, status
    
    try:
        now = time.time()
        if (now - float(_readiness_cache["checked_at"])) < 5.0:
            if _readiness_cache["ready"]:
                uptime = time.time() - _app_start_time
                return HealthResponse(
                    status=ComponentStatus.HEALTHY,
                    version=settings.app_version,
                    timestamp=datetime.now(timezone.utc),
                    uptime_seconds=round(uptime, 2),
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service not ready (cached probe)",
            )

        redis = await get_redis_pool()
        db_pool = await get_db_pool()
        async with db_pool.acquire() as db:
            await asyncio.wait_for(redis.ping(), timeout=settings.health_timeout_seconds)
            await asyncio.wait_for(db.fetchval("SELECT 1"), timeout=settings.health_timeout_seconds)
        satellite_engine = await get_satellite_engine()
        await asyncio.wait_for(
            satellite_engine.get_constellations(),
            timeout=settings.health_timeout_seconds,
        )

        _readiness_cache["checked_at"] = now
        _readiness_cache["ready"] = True
        uptime = time.time() - _app_start_time
        
        return HealthResponse(
            status=ComponentStatus.HEALTHY,
            version=settings.app_version,
            timestamp=datetime.now(timezone.utc),
            uptime_seconds=round(uptime, 2),
        )
        
    except Exception as e:
        _readiness_cache["checked_at"] = time.time()
        _readiness_cache["ready"] = False
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
