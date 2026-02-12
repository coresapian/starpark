# LinkSpot Backend Dockerfile
# FastAPI Application with Spatial Libraries
# Multi-stage build for development and production

# =============================================================================
# Base Stage - Common dependencies
# =============================================================================
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONFAULTHANDLER=1

# Install system dependencies
# - libpq-dev: PostgreSQL client libraries
# - gdal-bin, libgdal-dev: Geospatial libraries for PostGIS
# - build-essential: Compilation tools
# - curl: For health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV GDAL_VERSION=3.6.2 \
    CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

# Set working directory
WORKDIR /app

# =============================================================================
# Development Stage - With hot reload and dev tools
# =============================================================================
FROM base as development

# Install additional development dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt requirements-dev.txt* ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ -f requirements-dev.txt ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# Install additional dev tools
RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    pytest-cov \
    black \
    isort \
    flake8 \
    mypy \
    debugpy

# Copy application code (will be overridden by volume mount in compose)
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Expose port for FastAPI
EXPOSE 8000

# Development command with hot reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app"]

# =============================================================================
# Production Stage - Optimized for production
# =============================================================================
FROM base as production

# Create non-root user for security
RUN groupadd -r linkspot && useradd -r -g linkspot linkspot

# Copy requirements
COPY requirements.txt ./

# Install Python dependencies (production only)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Change ownership to non-root user
RUN chown -R linkspot:linkspot /app

# Create data directory with proper permissions
RUN mkdir -p /app/data && chown -R linkspot:linkspot /app/data

# Switch to non-root user
USER linkspot

# Expose port for FastAPI
EXPOSE 8000

# Production command without reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
