# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Pydantic models for request/response validation and serialization.
# All models use Pydantic v2 syntax.

"""Pydantic schemas for LinkSpot API."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Zone(str, Enum):
    """Coverage zone classification based on satellite visibility."""
    
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    BLOCKED = "blocked"


class GeoJSONGeometry(BaseModel):
    """GeoJSON Geometry object."""
    
    model_config = ConfigDict(extra="allow")
    
    type: Literal["Point", "Polygon", "MultiPolygon"] = Field(
        ..., description="Geometry type"
    )
    coordinates: list[Any] = Field(
        ..., description="Coordinates array"
    )


class GeoJSONFeature(BaseModel):
    """GeoJSON Feature object."""
    
    model_config = ConfigDict(extra="allow")
    
    type: Literal["Feature"] = Field(default="Feature", description="Feature type")
    geometry: GeoJSONGeometry = Field(
        ..., description="Geometry object"
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Feature properties"
    )
    id: Optional[str | int] = Field(
        default=None, description="Feature identifier"
    )


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection object."""
    
    model_config = ConfigDict(extra="allow")
    
    type: Literal["FeatureCollection"] = Field(
        default="FeatureCollection", description="Collection type"
    )
    features: list[GeoJSONFeature] = Field(
        default_factory=list, description="Array of features"
    )
    bbox: Optional[list[float]] = Field(
        default=None, description="Bounding box [minX, minY, maxX, maxY]"
    )


# ============================================================================
# Analysis Request/Response Models
# ============================================================================

class AnalyzeRequest(BaseModel):
    """Request model for single position analysis.
    
    Analyzes satellite visibility at a specific geographic location.
    """
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "lat": 40.7128,
            "lon": -74.0060,
            "elevation": 10.0,
            "timestamp": "2024-06-15T12:00:00Z"
        }
    })
    
    lat: float = Field(
        ..., 
        ge=-90.0, 
        le=90.0, 
        description="Latitude in decimal degrees (WGS84)"
    )
    lon: float = Field(
        ..., 
        ge=-180.0, 
        le=180.0, 
        description="Longitude in decimal degrees (WGS84)"
    )
    elevation: float = Field(
        default=0.0,
        ge=0.0,
        le=10000.0,
        description="Observer elevation above ground level in meters"
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Analysis timestamp (ISO 8601). Defaults to current time."
    )
    
    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        """Validate latitude range."""
        if not -90 <= v <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        return v
    
    @field_validator("lon")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        """Validate longitude range."""
        if not -180 <= v <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class AnalyzeResponse(BaseModel):
    """Response model for single position analysis.
    
    Contains satellite visibility metrics and obstruction analysis.
    """
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "zone": "good",
            "n_clear": 42,
            "n_total": 50,
            "obstruction_pct": 16.0,
            "blocked_azimuths": [[45.0, 60.0], [120.0, 135.0]],
            "timestamp": "2024-06-15T12:00:00Z",
            "lat": 40.7128,
            "lon": -74.0060
        }
    })
    
    zone: Zone = Field(
        ..., description="Coverage zone classification"
    )
    n_clear: int = Field(
        ..., ge=0, description="Number of satellites with clear line of sight"
    )
    n_total: int = Field(
        ..., ge=0, description="Total number of visible satellites"
    )
    obstruction_pct: float = Field(
        ..., ge=0.0, le=100.0, description="Percentage of sky obstructed"
    )
    blocked_azimuths: list[list[float]] = Field(
        default_factory=list,
        description="List of [start, end] azimuth ranges that are blocked (degrees)"
    )
    timestamp: datetime = Field(
        ..., description="Analysis timestamp (ISO 8601)"
    )
    lat: float = Field(
        ..., description="Latitude of analyzed position"
    )
    lon: float = Field(
        ..., description="Longitude of analyzed position"
    )
    elevation: float = Field(
        default=0.0, description="Observer elevation in meters"
    )
    
    @field_validator("blocked_azimuths")
    @classmethod
    def validate_azimuth_ranges(cls, v: list[list[float]]) -> list[list[float]]:
        """Validate azimuth ranges are within 0-360 degrees."""
        for range_pair in v:
            if len(range_pair) != 2:
                raise ValueError("Each azimuth range must have exactly 2 values")
            start, end = range_pair
            if not (0 <= start <= 360 and 0 <= end <= 360):
                raise ValueError("Azimuth values must be between 0 and 360 degrees")
        return v


class HeatmapRequest(BaseModel):
    """Request model for grid-based heatmap analysis.
    
    Generates a coverage heatmap around a center point.
    """
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "lat": 40.7128,
            "lon": -74.0060,
            "radius_m": 1000,
            "spacing_m": 100,
            "timestamp": "2024-06-15T12:00:00Z"
        }
    })
    
    lat: float = Field(
        ..., 
        ge=-90.0, 
        le=90.0, 
        description="Center latitude in decimal degrees"
    )
    lon: float = Field(
        ..., 
        ge=-180.0, 
        le=180.0, 
        description="Center longitude in decimal degrees"
    )
    radius_m: int = Field(
        ..., 
        ge=100, 
        le=10000, 
        description="Radius around center point in meters"
    )
    spacing_m: int = Field(
        ..., 
        ge=50, 
        le=500, 
        description="Grid spacing in meters"
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Analysis timestamp (ISO 8601). Defaults to current time."
    )
    include_geometry: bool = Field(
        default=True,
        description="Include full geometry in response (vs. just center points)"
    )


class HeatmapResponse(BaseModel):
    """Response model for heatmap analysis.
    
    Returns GeoJSON FeatureCollection with coverage data.
    """
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [-74.006, 40.7128]
                    },
                    "properties": {
                        "zone": "good",
                        "n_clear": 42,
                        "n_total": 50,
                        "obstruction_pct": 16.0
                    }
                }
            ],
            "metadata": {
                "center_lat": 40.7128,
                "center_lon": -74.0060,
                "radius_m": 1000,
                "spacing_m": 100,
                "total_points": 317,
                "timestamp": "2024-06-15T12:00:00Z"
            }
        }
    })
    
    type: Literal["FeatureCollection"] = Field(default="FeatureCollection")
    features: list[GeoJSONFeature] = Field(
        default_factory=list, description="Grid points with coverage data"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Heatmap generation metadata"
    )


# ============================================================================
# Satellite Models
# ============================================================================

class SatellitePosition(BaseModel):
    """Satellite position at a specific time."""
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "satellite_id": "STARLINK-1234",
            "norad_id": 12345,
            "azimuth": 45.5,
            "elevation": 25.3,
            "range_km": 550.0,
            "velocity_kms": 7.8
        }
    })
    
    satellite_id: str = Field(
        ..., description="Satellite identifier (name or catalog number)"
    )
    norad_id: Optional[int] = Field(
        default=None, description="NORAD catalog number"
    )
    azimuth: float = Field(
        ..., ge=0.0, le=360.0, description="Azimuth angle in degrees (0=N, 90=E)"
    )
    elevation: float = Field(
        ..., ge=-90.0, le=90.0, description="Elevation angle in degrees"
    )
    range_km: Optional[float] = Field(
        default=None, ge=0.0, description="Slant range in kilometers"
    )
    velocity_kms: Optional[float] = Field(
        default=None, description="Orbital velocity in km/s"
    )
    constellation: Optional[str] = Field(
        default=None, description="Constellation name (e.g., Starlink, OneWeb)"
    )


class VisibleSatellitesResponse(BaseModel):
    """Response model for visible satellites query."""
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "satellites": [
                {
                    "satellite_id": "STARLINK-1234",
                    "azimuth": 45.5,
                    "elevation": 25.3
                }
            ],
            "count": 1,
            "timestamp": "2024-06-15T12:00:00Z",
            "location": {"lat": 40.7128, "lon": -74.0060}
        }
    })
    
    satellites: list[SatellitePosition] = Field(
        default_factory=list, description="List of visible satellites"
    )
    count: int = Field(..., ge=0, description="Number of visible satellites")
    timestamp: datetime = Field(..., description="Query timestamp")
    location: dict[str, float] = Field(
        ..., description="Observer location {lat, lon}"
    )
    elevation_mask: float = Field(
        default=10.0, description="Elevation mask used for filtering"
    )


class ConstellationInfo(BaseModel):
    """Constellation information."""
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "Starlink",
            "operator": "SpaceX",
            "total_satellites": 5000,
            "active_satellites": 4500,
            "orbital_planes": 72,
            "altitude_km": 550,
            "inclination_deg": 53.0
        }
    })
    
    name: str = Field(..., description="Constellation name")
    operator: Optional[str] = Field(default=None, description="Operator company")
    total_satellites: int = Field(..., ge=0, description="Total satellites in constellation")
    active_satellites: int = Field(..., ge=0, description="Currently active satellites")
    orbital_planes: Optional[int] = Field(default=None, description="Number of orbital planes")
    altitude_km: Optional[float] = Field(default=None, description="Orbital altitude in km")
    inclination_deg: Optional[float] = Field(default=None, description="Orbital inclination in degrees")


class ConstellationListResponse(BaseModel):
    """Response model for constellation list."""
    
    constellations: list[ConstellationInfo] = Field(
        default_factory=list, description="Available constellations"
    )
    total_count: int = Field(..., ge=0, description="Total number of constellations")


# ============================================================================
# Health Models
# ============================================================================

class ComponentStatus(str, Enum):
    """Status of a system component."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentHealth(BaseModel):
    """Health status of a single component."""
    
    name: str = Field(..., description="Component name")
    status: ComponentStatus = Field(..., description="Component status")
    latency_ms: Optional[float] = Field(default=None, description="Response latency in ms")
    message: Optional[str] = Field(default=None, description="Status message")
    last_check: Optional[datetime] = Field(default=None, description="Last check timestamp")


class HealthResponse(BaseModel):
    """Basic health check response."""
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "healthy",
            "version": "1.0.0",
            "timestamp": "2024-06-15T12:00:00Z"
        }
    })
    
    status: ComponentStatus = Field(..., description="Overall service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(..., description="Health check timestamp")
    uptime_seconds: Optional[float] = Field(default=None, description="Service uptime in seconds")


class DetailedHealthResponse(HealthResponse):
    """Detailed health check response with component status."""
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "healthy",
            "version": "1.0.0",
            "timestamp": "2024-06-15T12:00:00Z",
            "components": [
                {
                    "name": "database",
                    "status": "healthy",
                    "latency_ms": 5.2
                },
                {
                    "name": "redis",
                    "status": "healthy",
                    "latency_ms": 1.1
                }
            ]
        }
    })
    
    components: list[ComponentHealth] = Field(
        default_factory=list, description="Individual component health"
    )
    environment: str = Field(..., description="Deployment environment")


# ============================================================================
# Error Models (RFC 7807 Problem Details)
# ============================================================================

class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details for HTTP APIs.
    
    Standardized error response format.
    """
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "type": "https://api.linkspot.io/errors/invalid-request",
            "title": "Invalid Request",
            "status": 400,
            "detail": "Latitude must be between -90 and 90 degrees",
            "instance": "/api/v1/analyze",
            "request_id": "req-123456"
        }
    })
    
    type: str = Field(
        ..., description="URI reference identifying the problem type"
    )
    title: str = Field(
        ..., description="Short human-readable summary"
    )
    status: int = Field(
        ..., description="HTTP status code"
    )
    detail: Optional[str] = Field(
        default=None, description="Human-readable explanation"
    )
    instance: Optional[str] = Field(
        default=None, description="URI reference identifying the occurrence"
    )
    request_id: Optional[str] = Field(
        default=None, description="Request ID for tracing"
    )
    errors: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Detailed validation errors"
    )
