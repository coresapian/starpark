# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Configuration management for LinkSpot FastAPI backend.
# Uses Pydantic Settings for environment-based configuration.

"""Configuration management for LinkSpot API."""

from functools import lru_cache
from typing import Optional

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables.
    Uses .env file for local development.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Application
    app_name: str = Field(default="LinkSpot API", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="production", description="Deployment environment")
    
    # Server
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=1, description="Number of worker processes")
    
    # Database
    database_url: PostgresDsn = Field(
        default="postgresql://linkspot:linkspot@localhost:5432/linkspot",
        description="PostgreSQL connection URL",
    )
    database_pool_size: int = Field(default=10, description="DB connection pool size")
    database_max_overflow: int = Field(default=20, description="DB max overflow connections")
    database_echo: bool = Field(default=False, description="Echo SQL queries")
    
    # Redis
    redis_url: RedisDsn = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_pool_size: int = Field(default=10, description="Redis connection pool size")
    redis_socket_timeout: float = Field(default=5.0, description="Redis socket timeout")
    redis_socket_connect_timeout: float = Field(default=5.0, description="Redis connect timeout")
    cache_ttl_seconds: int = Field(default=300, description="Default cache TTL in seconds")
    
    # API Keys
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    api_key: Optional[str] = Field(default=None, description="Optional API key for protected endpoints")
    
    # CORS
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS")
    cors_allow_methods: list[str] = Field(default=["*"], description="Allowed HTTP methods")
    cors_allow_headers: list[str] = Field(default=["*"], description="Allowed HTTP headers")
    
    # Rate Limiting
    rate_limit_requests: int = Field(default=100, description="Requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window in seconds")
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    
    # Satellite Engine
    elevation_mask_degrees: float = Field(
        default=10.0,
        description="Minimum elevation angle for satellite visibility",
    )
    tle_update_interval_hours: int = Field(
        default=6,
        description="TLE data update interval in hours",
    )
    max_satellites_per_query: int = Field(
        default=1000,
        description="Maximum satellites to return per query",
    )
    
    # Obstruction Engine
    ray_casting_resolution: int = Field(
        default=360,
        description="Number of azimuth rays for obstruction analysis",
    )
    max_building_height_meters: float = Field(
        default=500.0,
        description="Maximum building height for ray casting",
    )
    terrain_sample_distance_meters: float = Field(
        default=100.0,
        description="Distance between terrain samples",
    )
    
    # Heatmap Generation
    heatmap_max_radius_meters: int = Field(
        default=10000,
        description="Maximum heatmap radius in meters",
    )
    heatmap_min_spacing_meters: int = Field(
        default=50,
        description="Minimum grid spacing in meters",
    )
    heatmap_max_spacing_meters: int = Field(
        default=500,
        description="Maximum grid spacing in meters",
    )
    heatmap_max_points: int = Field(
        default=10000,
        description="Maximum number of points in a heatmap",
    )
    
    # Zone Classification
    zone_excellent_threshold: float = Field(
        default=0.9,
        description="Minimum clear ratio for excellent zone",
    )
    zone_good_threshold: float = Field(
        default=0.7,
        description="Minimum clear ratio for good zone",
    )
    zone_fair_threshold: float = Field(
        default=0.4,
        description="Minimum clear ratio for fair zone",
    )
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json",
        description="Log format: json or text",
    )
    log_request_body: bool = Field(default=False, description="Log request bodies")
    
    # Performance
    request_timeout_seconds: float = Field(
        default=30.0,
        description="Request timeout in seconds",
    )
    max_concurrent_requests: int = Field(
        default=100,
        description="Maximum concurrent requests",
    )
    
    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    @field_validator("cors_allow_methods", mode="before")
    @classmethod
    def parse_cors_methods(cls, v: str | list[str]) -> list[str]:
        """Parse CORS methods from string or list."""
        if isinstance(v, str):
            return [method.strip() for method in v.split(",")]
        return v
    
    @field_validator("cors_allow_headers", mode="before")
    @classmethod
    def parse_cors_headers(cls, v: str | list[str]) -> list[str]:
        """Parse CORS headers from string or list."""
        if isinstance(v, str):
            return [header.strip() for header in v.split(",")]
        return v
    
    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        allowed = {"development", "staging", "production", "testing"}
        if v.lower() not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v.lower()
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level value."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.
    
    Returns:
        Settings: Application settings singleton.
    """
    return Settings()


# Export settings instance for convenience
settings = get_settings()
