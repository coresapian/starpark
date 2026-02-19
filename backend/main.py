# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# FastAPI application entry point for LinkSpot backend.
# Provides satellite visibility analysis and coverage mapping.

"""LinkSpot FastAPI application entry point."""

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
        import json
        
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
                if record.exc_info:
                    log_data["exception"] = self.formatException(record.exc_info)
                
                return json.dumps(log_data)
        
        # Apply JSON formatter to root handler
        root_handler = logging.getLogger().handlers[0]
        root_handler.setFormatter(JSONFormatter())


configure_logging()
logger = logging.getLogger(__name__)


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
    
    try:
        # Initialize database pool
        await get_db_pool()
        logger.info("Database connection pool initialized")
        
        # Initialize Redis pool
        await get_redis_pool()
        logger.info("Redis connection pool initialized")
        
        logger.info("Application startup complete")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise
    
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
    
    return app


# Create application instance
app = create_application()


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions.
    
    Args:
        request: FastAPI request object.
        exc: The exception that was raised.
        
    Returns:
        JSONResponse: Error response following RFC 7807.
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:12])
    
    logger.error(
        f"[{request_id}] Unhandled exception: {exc}",
        exc_info=True,
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


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Handle ValueError exceptions.
    
    Args:
        request: FastAPI request object.
        exc: The ValueError that was raised.
        
    Returns:
        JSONResponse: Error response following RFC 7807.
    """
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


# ============================================================================
# Request Middleware
# ============================================================================

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    """Log all requests with timing information.
    
    Args:
        request: FastAPI request object.
        call_next: Next middleware/handler in chain.
        
    Returns:
        Response: The response from the next handler.
    """
    # Generate request ID
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:12])
    request.state.request_id = request_id
    
    # Log request start
    start_time = time.time()
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} - Started",
        extra={"request_id": request_id},
    )
    
    # Process request
    try:
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Log request completion
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Completed {response.status_code} in {duration_ms:.2f}ms",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )
        
        # Add request ID to response headers
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
            },
            exc_info=True,
        )
        raise


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
