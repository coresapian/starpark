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
LinkSpot Database Models

SQLAlchemy ORM models for PostgreSQL + PostGIS geospatial data storage.
Includes Building, TerrainTile, TLECache, and AnalysisCache models.
"""

import uuid
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Text,
    JSON,
    Index,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from geoalchemy2 import Geometry

Base = declarative_base()


class Building(Base):
    """
    Building model for storing 3D building footprint data.
    
    Stores building geometries as PostGIS Polygons with height information
    for line-of-sight calculations. Supports multiple data sources with
    confidence scoring for height data.
    
    Attributes:
        id: UUID primary key
        geometry: PostGIS Polygon geometry (SRID 4326)
        height: Building height in meters
        source: Data source identifier (e.g., 'microsoft_buildings', 'osm')
        source_id: Original ID from source dataset
        updated_at: Last update timestamp
        height_source: Source of height data (e.g., 'ml_inference', 'lidar')
        height_confidence: Confidence score for height (0.0-1.0)
    """
    
    __tablename__ = "buildings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geometry = Column(
        Geometry("POLYGON", srid=4326, spatial_index=False),
        nullable=False,
        comment="Building footprint polygon in WGS84"
    )
    height = Column(
        Float,
        nullable=False,
        comment="Building height in meters"
    )
    source = Column(
        String(64),
        nullable=False,
        index=True,
        comment="Data source identifier"
    )
    source_id = Column(
        String(128),
        nullable=False,
        comment="Original ID from source dataset"
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="Last update timestamp"
    )
    height_source = Column(
        String(64),
        nullable=True,
        comment="Source of height data"
    )
    height_confidence = Column(
        Float,
        nullable=True,
        comment="Confidence score for height (0.0-1.0)"
    )
    
    __table_args__ = (
        Index("idx_buildings_source_id", "source", "source_id", unique=True),
        Index("idx_buildings_height", "height"),
        {"comment": "3D building footprint data for line-of-sight calculations"},
    )
    
    def __repr__(self) -> str:
        return (
            f"<Building(id={self.id}, height={self.height:.1f}m, "
            f"source={self.source})>"
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert building to dictionary representation."""
        return {
            "id": str(self.id),
            "height": self.height,
            "source": self.source,
            "source_id": self.source_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "height_source": self.height_source,
            "height_confidence": self.height_confidence,
        }


class TerrainTile(Base):
    """
    Terrain tile metadata for SRTM/ASTER DEM data.
    
    Stores bounding boxes and S3 paths for terrain tiles used in
    elevation calculations. Links to raster data stored in object storage.
    
    Attributes:
        id: UUID primary key
        bbox: PostGIS Polygon bounding box (SRID 4326)
        s3_path: S3 URI to terrain raster file
        resolution_m: Spatial resolution in meters
        created_at: Record creation timestamp
    """
    
    __tablename__ = "terrain_tiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bbox = Column(
        Geometry("POLYGON", srid=4326, spatial_index=False),
        nullable=False,
        comment="Tile bounding box in WGS84"
    )
    s3_path = Column(
        String(512),
        nullable=False,
        comment="S3 URI to terrain raster file"
    )
    resolution_m = Column(
        Float,
        nullable=False,
        default=30.0,
        comment="Spatial resolution in meters"
    )
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        comment="Record creation timestamp"
    )
    
    __table_args__ = (
        {"comment": "Terrain tile metadata for elevation data"},
    )
    
    def __repr__(self) -> str:
        return f"<TerrainTile(id={self.id}, resolution={self.resolution_m}m)>"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert terrain tile to dictionary representation."""
        return {
            "id": str(self.id),
            "s3_path": self.s3_path,
            "resolution_m": self.resolution_m,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TLECache(Base):
    """
    Two-Line Element cache for satellite orbital data.
    
    Stores TLE data fetched from CelesTrak or other sources with
    fetch timestamp for cache invalidation.
    
    Attributes:
        id: UUID primary key
        constellation: Satellite constellation name (e.g., 'starlink', 'oneweb')
        tle_data: Raw TLE text data
        fetched_at: Timestamp when TLE was fetched
        expires_at: Cache expiration timestamp
    """
    
    __tablename__ = "tle_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    constellation = Column(
        String(64),
        nullable=False,
        index=True,
        unique=True,
        comment="Satellite constellation name"
    )
    tle_data = Column(
        Text,
        nullable=False,
        comment="Raw TLE text data"
    )
    fetched_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        comment="Timestamp when TLE was fetched"
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Cache expiration timestamp"
    )
    
    __table_args__ = (
        Index("idx_tle_cache_fetched_at", "fetched_at"),
        {"comment": "Two-Line Element cache for satellite orbital data"},
    )
    
    def __repr__(self) -> str:
        return f"<TLECache(constellation={self.constellation}, fetched_at={self.fetched_at})>"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert TLE cache to dictionary representation."""
        return {
            "id": str(self.id),
            "constellation": self.constellation,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class AnalysisCache(Base):
    """
    Cached analysis results for geospatial queries.
    
    Stores pre-computed analysis results keyed by geohash for
    fast retrieval of frequently-accessed locations.
    
    Attributes:
        id: UUID primary key
        geohash: Geohash string (precision 6 = ~1.2km x 0.6km)
        lat: Latitude of cache center
        lon: Longitude of cache center
        result_json: JSON analysis result data
        computed_at: Timestamp when analysis was computed
        expires_at: Cache expiration timestamp
        access_count: Number of times cache was accessed
        last_accessed_at: Last access timestamp
    """
    
    __tablename__ = "analysis_cache"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geohash = Column(
        String(12),
        nullable=False,
        index=True,
        unique=True,
        comment="Geohash string (precision 6 = ~1.2km x 0.6km)"
    )
    lat = Column(
        Float,
        nullable=False,
        comment="Latitude of cache center"
    )
    lon = Column(
        Float,
        nullable=False,
        comment="Longitude of cache center"
    )
    result_json = Column(
        JSONB,
        nullable=False,
        comment="JSON analysis result data"
    )
    computed_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        comment="Timestamp when analysis was computed"
    )
    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Cache expiration timestamp"
    )
    access_count = Column(
        Float,
        default=0,
        nullable=False,
        comment="Number of times cache was accessed"
    )
    last_accessed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last access timestamp"
    )
    
    __table_args__ = (
        Index("idx_analysis_cache_lat_lon", "lat", "lon"),
        Index("idx_analysis_cache_computed_at", "computed_at"),
        Index("idx_analysis_cache_expires_at", "expires_at"),
        {"comment": "Cached analysis results for geospatial queries"},
    )
    
    def __repr__(self) -> str:
        return f"<AnalysisCache(geohash={self.geohash}, computed_at={self.computed_at})>"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert analysis cache to dictionary representation."""
        return {
            "id": str(self.id),
            "geohash": self.geohash,
            "lat": self.lat,
            "lon": self.lon,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_count": self.access_count,
            "last_accessed_at": (
                self.last_accessed_at.isoformat() if self.last_accessed_at else None
            ),
        }


# Export all models
__all__ = [
    "Base",
    "Building",
    "TerrainTile",
    "TLECache",
    "AnalysisCache",
]
