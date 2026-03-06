# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# FastAPI application entry point for LinkSpot backend.
# Provides satellite visibility analysis and coverage mapping.

"""LinkSpot FastAPI application entry point."""

import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from config import settings
from dependencies import close_dependencies, get_db_pool, get_redis_pool
from middleware.rate_limit import RateLimitMiddleware
from models.schemas import ProblemDetail
from routers import analysis, health, route, satellites

# ============================================================================
# Logging Configuration
# ============================================================================


def configure_logging() -> None:
    """Configure structured logging for the application."""
    log_level = getattr(logging, settings.log_level)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Set specific log levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Configure JSON logging if requested
    if settings.log_format == "json":

        class JSONFormatter(logging.Formatter):
            """JSON log formatter for structured logging."""

            def format(self, record: logging.LogRecord) -> str:
                log_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }

                # Add extra fields if present
                if hasattr(record, "request_id"):
                    log_data["request_id"] = record.request_id
                if hasattr(record, "duration_ms"):
                    log_data["duration_ms"] = record.duration_ms
                if hasattr(record, "category"):
                    log_data["category"] = record.category
                if hasattr(record, "status_code"):
                    log_data["status_code"] = record.status_code
                if hasattr(record, "status_class"):
                    log_data["status_class"] = record.status_class
                if hasattr(record, "client_ip"):
                    log_data["client_ip"] = record.client_ip
                if record.exc_info:
                    log_data["exception"] = self.formatException(record.exc_info)

                return json.dumps(log_data)

        # Apply JSON formatter to root handler
        root_handler = logging.getLogger().handlers[0]
        root_handler.setFormatter(JSONFormatter())


configure_logging()
logger = logging.getLogger(__name__)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:12])

    category = "internal_error"
    logger.error(
        f"[{request_id}] Unhandled exception [{category}]: {exc}",
        exc_info=True,
        extra={"request_id": request_id, "category": category},
    )

    problem = ProblemDetail(
        type="https://api.linkspot.io/errors/internal-server-error",
        title="Internal Server Error",
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. Please try again later.",
        instance=str(request.url.path),
        request_id=request_id,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=problem.model_dump(exclude_none=True),
    )


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Handle ValueError exceptions."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:12])

    logger.warning(f"[{request_id}] Value error: {exc}")

    problem = ProblemDetail(
        type="https://api.linkspot.io/errors/invalid-value",
        title="Invalid Value",
        status=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
        instance=str(request.url.path),
        request_id=request_id,
    )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=problem.model_dump(exclude_none=True),
    )


async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    """Log all requests with timing information."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:12])
    request.state.request_id = request_id

    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} - Started",
        extra={"request_id": request_id, "client_ip": client_ip},
    )
    # TODO: Avoid logging request bodies for all verbs by default; this currently adds per-request overhead.

    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        status_class = f"{response.status_code // 100}xx"
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Completed {response.status_code} in {duration_ms:.2f}ms",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
                "status_code": response.status_code,
                "status_class": status_class,
                "client_ip": client_ip,
            },
        )
        # TODO: Add structured fields for client IP and status class summaries.
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Failed in {duration_ms:.2f}ms: {e}",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
                "status_class": "5xx",
                "client_ip": client_ip,
                "category": "request_failure",
            },
            exc_info=True,
        )
        raise


# ============================================================================
# Application Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Handles startup and shutdown events.

    Args:
        app: FastAPI application instance.

    Yields:
        None
    """
    # Startup
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version} "
        f"in {settings.environment} mode"
    )
    startup_warnings: list[tuple[str, Exception]] = []

    # Initialize database pool (degraded startup allowed).
    try:
        await get_db_pool()
        logger.info("Database connection pool initialized")
    except Exception as e:
        startup_warnings.append(("database", e))
        logger.warning("Database init failed; continuing in degraded mode: %s", e)

    # Initialize Redis pool (fallbacks handled in dependency module).
    try:
        await get_redis_pool()
        logger.info("Redis connection pool initialized")
    except Exception as e:
        startup_warnings.append(("redis", e))
        logger.warning("Redis init failed; continuing in degraded mode: %s", e)

    app.state.startup_warnings = startup_warnings
    if startup_warnings:
        logger.warning(
            "Application started in degraded mode with %d dependency warnings",
            len(startup_warnings),
        )
    else:
        logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down application...")

    try:
        await close_dependencies()
        logger.info("All connections closed")

    except Exception as e:
        logger.error(f"Shutdown error: {e}", exc_info=True)

    logger.info("Application shutdown complete")


# ============================================================================
# FastAPI Application
# ============================================================================


def create_application() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        FastAPI: Configured application instance.
    """
    # TODO: Keep doc endpoints behind an explicit debug or ops flag instead of reusing debug alone.
    app = FastAPI(
        title=settings.app_name,
        description="""
        LinkSpot API provides satellite visibility analysis and coverage mapping.
        
        ## Features
        
        - **Single Position Analysis**: Analyze satellite visibility at a specific location
        - **Heatmap Generation**: Generate coverage heatmaps for geographic areas
        - **Satellite Tracking**: Query visible satellites from any location
        - **Constellation Info**: Get information about satellite constellations
        
        ## Performance
        
        - Analysis endpoints: < 1 second (warm cache)
        - Heatmap generation: < 5 seconds (cold), < 2 seconds (warm)
        - 99th percentile: < 8 seconds
        
        ## Authentication
        
        API key authentication is optional and can be configured via environment variables.
        """,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Add GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Add rate limiting middleware
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )

    # Include routers
    app.include_router(analysis.router)
    app.include_router(satellites.router)
    app.include_router(route.router)
    app.include_router(health.router)
    # TODO: Standardize route versioning and remove direct root route coupling from app setup.

    app.add_exception_handler(Exception, global_exception_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.middleware("http")(request_logging_middleware)

    return app


# Create application instance
app = create_application()


# ============================================================================
# Root Endpoint
# ============================================================================


@app.get(
    "/",
    tags=["Root"],
    summary="API root endpoint",
    description="Returns basic API information and links to documentation.",
)
async def root() -> dict[str, Any]:
    """Root endpoint returning API information.

    Returns:
        dict: API information.
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "documentation": {
            "swagger": "/docs" if settings.debug else None,
            "redoc": "/redoc" if settings.debug else None,
            "openapi": "/openapi.json" if settings.debug else None,
        },
        "endpoints": {
            "health": "/api/v1/health",
            "analyze": "/api/v1/analyze",
            "heatmap": "/api/v1/heatmap",
            "satellites": "/api/v1/satellites",
        },
    }


@app.get(
    "/api/v1",
    tags=["Root"],
    summary="API version info",
    description="Returns API version and available endpoints.",
)
async def api_info() -> dict[str, Any]:
    """API version information endpoint.

    Returns:
        dict: API version and endpoint information.
    """
    return {
        "version": "v1",
        "name": settings.app_name,
        "description": "Satellite visibility analysis API",
        "endpoints": [
            {
                "path": "/api/v1/health",
                "methods": ["GET"],
                "description": "Health check endpoints",
            },
            {
                "path": "/api/v1/analyze",
                "methods": ["POST"],
                "description": "Single position analysis",
            },
            {
                "path": "/api/v1/heatmap",
                "methods": ["POST"],
                "description": "Grid-based heatmap generation",
            },
            {
                "path": "/api/v1/satellites",
                "methods": ["GET"],
                "description": "Visible satellites query",
            },
            {
                "path": "/api/v1/satellites/constellation",
                "methods": ["GET"],
                "description": "Constellation information",
            },
            {
                "path": "/api/v1/satellites/constellation/map",
                "methods": ["GET"],
                "description": "Constellation map subpoint positions",
            },
        ],
    }


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=settings.workers if not settings.debug else 1,
        log_level=settings.log_level.lower(),
        access_log=settings.debug,
    )
