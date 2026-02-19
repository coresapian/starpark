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
LinkSpot Spatial Query Functions

High-performance spatial queries for PostGIS with support for:
- Radius-based building queries
- Bounding box queries
- Bulk inserts
- Terrain tile lookups
- Analysis result caching
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID

import geopandas as gpd
import pygeohash as pgh
from geoalchemy2 import functions as geo_funcs
from geoalchemy2.shape import to_shape, from_shape
from shapely.geometry import Point, Polygon, mapping
from shapely import wkt
from sqlalchemy import select, insert, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import Building, TerrainTile, TLECache, AnalysisCache

logger = logging.getLogger(__name__)


# =============================================================================
# Building Queries
# =============================================================================


def _validate_lat_lon(lat: float, lon: float) -> None:
    if not (-90.0 <= float(lat) <= 90.0):
        raise ValueError(f"Invalid latitude: {lat}")
    if not (-180.0 <= float(lon) <= 180.0):
        raise ValueError(f"Invalid longitude: {lon}")


def _validate_radius(radius_m: float) -> None:
    if not (0.0 < float(radius_m) <= 100000.0):
        raise ValueError(f"Invalid radius: {radius_m}")


def _validate_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> tuple[float, float, float, float]:
    _validate_lat_lon(min_lat, min_lon)
    _validate_lat_lon(max_lat, max_lon)
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    return min_lat, min_lon, max_lat, max_lon

def get_buildings_in_radius(
    session: Session,
    lat: float,
    lon: float,
    radius_m: float,
    min_height: Optional[float] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """
    Get buildings within a radius using PostGIS spatial query.
    
    Uses ST_DWithin for efficient indexed radius queries. Performance
    target: < 3 seconds for cold queries, < 500ms for hot cache.
    
    Args:
        session: SQLAlchemy session
        lat: Center latitude (WGS84)
        lon: Center longitude (WGS84)
        radius_m: Search radius in meters
        min_height: Optional minimum building height filter
        limit: Maximum number of results
        
    Returns:
        List of building dictionaries with geometry as GeoJSON
        
    Example:
        >>> buildings = get_buildings_in_radius(
        ...     session, 37.7749, -122.4194, 500.0
        ... )
    """
    _validate_lat_lon(lat, lon)
    _validate_radius(radius_m)
    # Create center point
    # TODO: Add async context timeout so one slow route-analysis request can't consume DB workers indefinitely.
    center_point = f"SRID=4326;POINT({lon} {lat})"
    
    # Build query with ST_DWithin for indexed search
    # TODO: Add explicit ST_DWithin input sanitization if radius_m gets set from untrusted sources.
    query = (
        select(
            Building.id,
            Building.height,
            Building.source,
            Building.source_id,
            Building.height_source,
            Building.height_confidence,
            geo_funcs.ST_AsGeoJSON(Building.geometry).label("geometry_geojson"),
        )
        .where(
            geo_funcs.ST_DWithin(
                Building.geometry,
                geo_funcs.ST_GeogFromText(center_point),
                radius_m,
            )
        )
        .order_by(
            geo_funcs.ST_Distance(
                Building.geometry,
                geo_funcs.ST_GeogFromText(center_point),
            )
        )
        .limit(limit)
    )
    
    # Apply height filter if specified
    if min_height is not None:
        query = query.where(Building.height >= min_height)
    
    # TODO: Add execution-time budget for this query when max range is unexpectedly large.
    results = session.execute(query).fetchall()
    
    buildings = []
    for row in results:
        building = {
            "id": str(row.id),
            "height": row.height,
            "source": row.source,
            "source_id": row.source_id,
            "height_source": row.height_source,
            "height_confidence": row.height_confidence,
            "geometry": row.geometry_geojson,
        }
        buildings.append(building)
    
    logger.debug(
        f"Found {len(buildings)} buildings within {radius_m}m of ({lat}, {lon})"
    )
    return buildings


async def get_buildings_in_radius_async(
    session: AsyncSession,
    lat: float,
    lon: float,
    radius_m: float,
    min_height: Optional[float] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """
    Async version of get_buildings_in_radius.
    
    Args:
        session: SQLAlchemy async session
        lat: Center latitude (WGS84)
        lon: Center longitude (WGS84)
        radius_m: Search radius in meters
        min_height: Optional minimum building height filter
        limit: Maximum number of results
        
    Returns:
        List of building dictionaries with geometry as GeoJSON
    """
    _validate_lat_lon(lat, lon)
    _validate_radius(radius_m)
    center_point = f"SRID=4326;POINT({lon} {lat})"
    
    query = (
        select(
            Building.id,
            Building.height,
            Building.source,
            Building.source_id,
            Building.height_source,
            Building.height_confidence,
            geo_funcs.ST_AsGeoJSON(Building.geometry).label("geometry_geojson"),
        )
        .where(
            geo_funcs.ST_DWithin(
                Building.geometry,
                geo_funcs.ST_GeogFromText(center_point),
                radius_m,
            )
        )
        .order_by(
            geo_funcs.ST_Distance(
                Building.geometry,
                geo_funcs.ST_GeogFromText(center_point),
            )
        )
        .limit(limit)
    )
    
    if min_height is not None:
        query = query.where(Building.height >= min_height)
    
    result = await session.execute(query)
    rows = result.fetchall()
    
    buildings = []
    for row in rows:
        building = {
            "id": str(row.id),
            "height": row.height,
            "source": row.source,
            "source_id": row.source_id,
            "height_source": row.height_source,
            "height_confidence": row.height_confidence,
            "geometry": row.geometry_geojson,
        }
        buildings.append(building)
    
    logger.debug(
        f"Found {len(buildings)} buildings within {radius_m}m of ({lat}, {lon})"
    )
    return buildings


def get_buildings_in_bbox(
    session: Session,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    min_height: Optional[float] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """
    Get buildings within a bounding box.
    
    Uses PostGIS && operator for efficient bounding box intersection
    with GiST index support.
    
    Args:
        session: SQLAlchemy session
        min_lat: Minimum latitude
        min_lon: Minimum longitude
        max_lat: Maximum latitude
        max_lon: Maximum longitude
        min_height: Optional minimum building height filter
        limit: Maximum number of results
        
    Returns:
        List of building dictionaries with geometry as GeoJSON
    """
    min_lat, min_lon, max_lat, max_lon = _validate_bbox(min_lat, min_lon, max_lat, max_lon)
    # Create bounding box polygon
    bbox_wkt = f"SRID=4326;POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    
    query = (
        select(
            Building.id,
            Building.height,
            Building.source,
            Building.source_id,
            Building.height_source,
            Building.height_confidence,
            geo_funcs.ST_AsGeoJSON(Building.geometry).label("geometry_geojson"),
        )
        .where(
            Building.geometry.intersects(geo_funcs.ST_GeomFromText(bbox_wkt))
        )
        .limit(limit)
    )
    
    if min_height is not None:
        query = query.where(Building.height >= min_height)
    
    results = session.execute(query).fetchall()
    
    buildings = []
    for row in results:
        building = {
            "id": str(row.id),
            "height": row.height,
            "source": row.source,
            "source_id": row.source_id,
            "height_source": row.height_source,
            "height_confidence": row.height_confidence,
            "geometry": row.geometry_geojson,
        }
        buildings.append(building)
    
    logger.debug(
        f"Found {len(buildings)} buildings in bbox "
        f"({min_lat}, {min_lon}, {max_lat}, {max_lon})"
    )
    return buildings


async def get_buildings_in_bbox_async(
    session: AsyncSession,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    min_height: Optional[float] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """Async version of get_buildings_in_bbox."""
    min_lat, min_lon, max_lat, max_lon = _validate_bbox(min_lat, min_lon, max_lat, max_lon)
    bbox_wkt = f"SRID=4326;POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
    
    query = (
        select(
            Building.id,
            Building.height,
            Building.source,
            Building.source_id,
            Building.height_source,
            Building.height_confidence,
            geo_funcs.ST_AsGeoJSON(Building.geometry).label("geometry_geojson"),
        )
        .where(
            Building.geometry.intersects(geo_funcs.ST_GeomFromText(bbox_wkt))
        )
        .limit(limit)
    )
    
    if min_height is not None:
        query = query.where(Building.height >= min_height)
    
    result = await session.execute(query)
    rows = result.fetchall()
    
    buildings = []
    for row in rows:
        building = {
            "id": str(row.id),
            "height": row.height,
            "source": row.source,
            "source_id": row.source_id,
            "height_source": row.height_source,
            "height_confidence": row.height_confidence,
            "geometry": row.geometry_geojson,
        }
        buildings.append(building)
    
    return buildings


def insert_buildings_batch(
    session: Session,
    buildings_gdf: gpd.GeoDataFrame,
    source: str,
    batch_size: int = 1000,
) -> int:
    """
    Bulk insert buildings from GeoDataFrame.
    
    Efficiently inserts building data from a GeoPandas GeoDataFrame
    with geometry converted to PostGIS format.
    
    Args:
        session: SQLAlchemy session
        buildings_gdf: GeoDataFrame with building data
        source: Data source identifier
        batch_size: Number of records per batch
        
    Returns:
        Number of buildings inserted
        
    Example:
        >>> gdf = gpd.read_file("buildings.geojson")
        >>> count = insert_buildings_batch(session, gdf, "microsoft_buildings")
    """
    if buildings_gdf.empty:
        logger.warning("Empty GeoDataFrame, no buildings to insert")
        return 0
    
    required_cols = ["geometry", "height"]
    for col in required_cols:
        if col not in buildings_gdf.columns:
            raise ValueError(f"Required column '{col}' not found in GeoDataFrame")
    # TODO: Add async-compatible validation before float casting to avoid transaction rollback storms.
    # TODO: Add per-column validation/coercion for nullable/non-numeric heights before casting to float.
    
    # Ensure CRS is WGS84
    if buildings_gdf.crs is not None and buildings_gdf.crs.to_epsg() != 4326:
        buildings_gdf = buildings_gdf.to_crs(epsg=4326)
    
    inserted_count = 0
    
    # Process in batches
    for i in range(0, len(buildings_gdf), batch_size):
        batch = buildings_gdf.iloc[i:i + batch_size]
        
        buildings_data = []
        for idx, row in batch.iterrows():
            # Convert geometry to WKT
            # TODO: Skip invalid/empty geometries explicitly so corrupted batches don't abort the full load.
            geom_wkt = row.geometry.wkt if hasattr(row.geometry, 'wkt') else str(row.geometry)
            
            building_data = {
                "geometry": f"SRID=4326;{geom_wkt}",
                "height": float(row["height"]),
                "source": source,
                "source_id": str(row.get("source_id", idx)),
                "height_source": row.get("height_source"),
                "height_confidence": float(row.get("height_confidence", 0.5)),
            }
            buildings_data.append(building_data)
        
        # Bulk insert with ON CONFLICT handling
        stmt = pg_insert(Building).values(buildings_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "source_id"],
            set_={
                "geometry": stmt.excluded.geometry,
                "height": stmt.excluded.height,
                "height_source": stmt.excluded.height_source,
                "height_confidence": stmt.excluded.height_confidence,
                "updated_at": datetime.utcnow(),
            }
        )
        
        result = session.execute(stmt)
        inserted_count += len(buildings_data)
        
        logger.debug(f"Inserted batch of {len(buildings_data)} buildings")
    
    logger.info(f"Total buildings inserted/updated: {inserted_count}")
    return inserted_count


async def insert_buildings_batch_async(
    session: AsyncSession,
    buildings_gdf: gpd.GeoDataFrame,
    source: str,
    batch_size: int = 1000,
) -> int:
    """Async version of insert_buildings_batch."""
    if buildings_gdf.empty:
        logger.warning("Empty GeoDataFrame, no buildings to insert")
        return 0
    
    required_cols = ["geometry", "height"]
    for col in required_cols:
        if col not in buildings_gdf.columns:
            raise ValueError(f"Required column '{col}' not found in GeoDataFrame")
    
    if buildings_gdf.crs is not None and buildings_gdf.crs.to_epsg() != 4326:
        buildings_gdf = buildings_gdf.to_crs(epsg=4326)
    
    inserted_count = 0
    
    for i in range(0, len(buildings_gdf), batch_size):
        batch = buildings_gdf.iloc[i:i + batch_size]
        
        buildings_data = []
        for idx, row in batch.iterrows():
            # TODO: Guard against zero-area/invalid geometries to keep ON CONFLICT update semantics predictable.
            geom_wkt = row.geometry.wkt if hasattr(row.geometry, 'wkt') else str(row.geometry)
            
            building_data = {
                "geometry": f"SRID=4326;{geom_wkt}",
                "height": float(row["height"]),
                "source": source,
                "source_id": str(row.get("source_id", idx)),
                "height_source": row.get("height_source"),
                "height_confidence": float(row.get("height_confidence", 0.5)),
            }
            buildings_data.append(building_data)
        
        stmt = pg_insert(Building).values(buildings_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "source_id"],
            set_={
                "geometry": stmt.excluded.geometry,
                "height": stmt.excluded.height,
                "height_source": stmt.excluded.height_source,
                "height_confidence": stmt.excluded.height_confidence,
                "updated_at": datetime.utcnow(),
            }
        )
        
        await session.execute(stmt)
        inserted_count += len(buildings_data)
    
    return inserted_count


# =============================================================================
# Terrain Tile Queries
# =============================================================================

def get_terrain_tile(
    session: Session,
    lat: float,
    lon: float,
) -> Optional[Dict[str, Any]]:
    """
    Get terrain tile metadata for a location.
    
    Finds the terrain tile that contains the given coordinates.
    
    Args:
        session: SQLAlchemy session
        lat: Latitude
        lon: Longitude
        
    Returns:
        Terrain tile dictionary or None if not found
    """
    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    
    query = (
        select(TerrainTile)
        .where(
            TerrainTile.bbox.contains(geo_funcs.ST_GeomFromText(point_wkt))
        )
        .limit(1)
    )
    
    result = session.execute(query).scalar_one_or_none()
    
    if result:
        return {
            "id": str(result.id),
            "s3_path": result.s3_path,
            "resolution_m": result.resolution_m,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        }
    
    return None


async def get_terrain_tile_async(
    session: AsyncSession,
    lat: float,
    lon: float,
) -> Optional[Dict[str, Any]]:
    """Async version of get_terrain_tile."""
    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    
    query = (
        select(TerrainTile)
        .where(
            TerrainTile.bbox.contains(geo_funcs.ST_GeomFromText(point_wkt))
        )
        .limit(1)
    )
    
    result = await session.execute(query)
    tile = result.scalar_one_or_none()
    
    if tile:
        return {
            "id": str(tile.id),
            "s3_path": tile.s3_path,
            "resolution_m": tile.resolution_m,
            "created_at": tile.created_at.isoformat() if tile.created_at else None,
        }
    
    return None


# =============================================================================
# Analysis Cache Queries
# =============================================================================

def get_cached_analysis(
    session: Session,
    geohash: str,
    max_age_hours: Optional[int] = 24,
) -> Optional[Dict[str, Any]]:
    """
    Get cached analysis result by geohash.
    
    Retrieves cached analysis if it exists and is not expired.
    Updates access count and last accessed timestamp.
    
    Args:
        session: SQLAlchemy session
        geohash: Geohash string (typically precision 6)
        max_age_hours: Maximum age of cache in hours
        
    Returns:
        Cached analysis result or None if not found/expired
    """
    try:
        pgh.decode_exactly(geohash)
    except Exception:
        return None
    query = select(AnalysisCache).where(AnalysisCache.geohash == geohash)
    
    if max_age_hours:
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        # TODO: Use cutoff_time in query to ensure explicit expiry floor is enforced consistently.
        query = query.where(
            (AnalysisCache.expires_at.is_(None)) | 
            (AnalysisCache.expires_at > datetime.utcnow())
        )
    
    result = session.execute(query).scalar_one_or_none()
    
    if result:
        # Update access statistics
        result.access_count += 1
        result.last_accessed_at = datetime.utcnow()
        session.flush()
        
        return {
            "id": str(result.id),
            "geohash": result.geohash,
            "lat": result.lat,
            "lon": result.lon,
            "result": result.result_json,
            "computed_at": result.computed_at.isoformat() if result.computed_at else None,
            "access_count": result.access_count,
        }
    
        # TODO: Add cache metrics for stale-hit vs miss behavior in endpoint-level SLOs.
        return None


async def get_cached_analysis_async(
    session: AsyncSession,
    geohash: str,
    max_age_hours: Optional[int] = 24,
) -> Optional[Dict[str, Any]]:
    """Async version of get_cached_analysis."""
    query = select(AnalysisCache).where(AnalysisCache.geohash == geohash)
    
    if max_age_hours:
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        query = query.where(
            (AnalysisCache.expires_at.is_(None)) | 
            (AnalysisCache.expires_at > datetime.utcnow())
        )
    
    result = await session.execute(query)
    cache = result.scalar_one_or_none()
    
    if cache:
        cache.access_count += 1
        cache.last_accessed_at = datetime.utcnow()
        await session.flush()
        
        return {
            "id": str(cache.id),
            "geohash": cache.geohash,
            "lat": cache.lat,
            "lon": cache.lon,
            "result": cache.result_json,
            "computed_at": cache.computed_at.isoformat() if cache.computed_at else None,
            "access_count": cache.access_count,
        }
    
    return None


def cache_analysis_result(
    session: Session,
    geohash: str,
    lat: float,
    lon: float,
    result: Dict[str, Any],
    ttl_hours: int = 24,
) -> UUID:
    """
    Store analysis result in cache.
    
    Args:
        session: SQLAlchemy session
        geohash: Geohash string for cache key
        lat: Latitude of analysis center
        lon: Longitude of analysis center
        result: Analysis result dictionary
        ttl_hours: Cache TTL in hours
        
    Returns:
        UUID of cached analysis record
    """
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    
    # Use upsert for cache
    stmt = pg_insert(AnalysisCache).values(
        geohash=geohash,
        lat=lat,
        lon=lon,
        result_json=result,
        computed_at=datetime.utcnow(),
        expires_at=expires_at,
        access_count=0,
    )
    
    stmt = stmt.on_conflict_do_update(
        index_elements=["geohash"],
        set_={
            "lat": stmt.excluded.lat,
            "lon": stmt.excluded.lon,
            "result_json": stmt.excluded.result_json,
            "computed_at": stmt.excluded.computed_at,
            "expires_at": stmt.excluded.expires_at,
            "access_count": 0,
            "last_accessed_at": None,
        }
    )
    
    # TODO: Capture upsert rowcount and raise a typed error when cache write is a no-op.
    result_exec = session.execute(stmt)
    
    # Get the ID of the inserted/updated record
    cache_record = session.execute(
        select(AnalysisCache).where(AnalysisCache.geohash == geohash)
    ).scalar_one()
    
    logger.debug(f"Cached analysis result for geohash {geohash}")
    
    return cache_record.id


async def cache_analysis_result_async(
    session: AsyncSession,
    geohash: str,
    lat: float,
    lon: float,
    result: Dict[str, Any],
    ttl_hours: int = 24,
) -> UUID:
    """Async version of cache_analysis_result."""
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    
    stmt = pg_insert(AnalysisCache).values(
        geohash=geohash,
        lat=lat,
        lon=lon,
        result_json=result,
        computed_at=datetime.utcnow(),
        expires_at=expires_at,
        access_count=0,
    )
    
    stmt = stmt.on_conflict_do_update(
        index_elements=["geohash"],
        set_={
            "lat": stmt.excluded.lat,
            "lon": stmt.excluded.lon,
            "result_json": stmt.excluded.result_json,
            "computed_at": stmt.excluded.computed_at,
            "expires_at": stmt.excluded.expires_at,
            "access_count": 0,
            "last_accessed_at": None,
        }
    )
    
    await session.execute(stmt)
    
    # TODO: Avoid extra SELECT by using `RETURNING id` on upsert and reusing row data.
    result_exec = await session.execute(
        select(AnalysisCache).where(AnalysisCache.geohash == geohash)
    )
    cache_record = result_exec.scalar_one()
    
    return cache_record.id


# =============================================================================
# TLE Cache Queries
# =============================================================================

def get_cached_tles(
    session: Session,
    constellation: str,
    max_age_hours: int = 4,
) -> Optional[str]:
    """
    Get cached TLE data for a constellation.
    
    Args:
        session: SQLAlchemy session
        constellation: Constellation name (e.g., 'starlink')
        max_age_hours: Maximum age of TLE data in hours
        
    Returns:
        Raw TLE text or None if not found/expired
    """
    cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
    
    query = (
        select(TLECache)
        .where(TLECache.constellation == constellation)
        .where(
            (TLECache.expires_at.is_(None)) |
            (TLECache.expires_at > datetime.utcnow())
        )
        .where(TLECache.fetched_at > cutoff_time)
    )
    
    result = session.execute(query).scalar_one_or_none()
    
    if result:
        return result.tle_data
    
    return None


async def get_cached_tles_async(
    session: AsyncSession,
    constellation: str,
    max_age_hours: int = 4,
) -> Optional[str]:
    """Async version of get_cached_tles."""
    cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
    
    query = (
        select(TLECache)
        .where(TLECache.constellation == constellation)
        .where(
            (TLECache.expires_at.is_(None)) |
            (TLECache.expires_at > datetime.utcnow())
        )
        .where(TLECache.fetched_at > cutoff_time)
    )
    
    result = await session.execute(query)
    cache = result.scalar_one_or_none()
    
    if cache:
        return cache.tle_data
    
    return None


def cache_tles(
    session: Session,
    constellation: str,
    tle_data: str,
    ttl_hours: int = 4,
) -> None:
    """
    Cache TLE data for a constellation.
    
    Args:
        session: SQLAlchemy session
        constellation: Constellation name
        tle_data: Raw TLE text data
        ttl_hours: Cache TTL in hours
    """
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    
    stmt = pg_insert(TLECache).values(
        constellation=constellation,
        tle_data=tle_data,
        fetched_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    
    stmt = stmt.on_conflict_do_update(
        index_elements=["constellation"],
        set_={
            "tle_data": stmt.excluded.tle_data,
            "fetched_at": stmt.excluded.fetched_at,
            "expires_at": stmt.excluded.expires_at,
        }
    )
    
    session.execute(stmt)
    logger.debug(f"Cached TLE data for constellation {constellation}")


async def cache_tles_async(
    session: AsyncSession,
    constellation: str,
    tle_data: str,
    ttl_hours: int = 4,
) -> None:
    """Async version of cache_tles."""
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    
    stmt = pg_insert(TLECache).values(
        constellation=constellation,
        tle_data=tle_data,
        fetched_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    
    stmt = stmt.on_conflict_do_update(
        index_elements=["constellation"],
        set_={
            "tle_data": stmt.excluded.tle_data,
            "fetched_at": stmt.excluded.fetched_at,
            "expires_at": stmt.excluded.expires_at,
        }
    )
    
    await session.execute(stmt)


# =============================================================================
# Utility Functions
# =============================================================================

def compute_geohash(lat: float, lon: float, precision: int = 6) -> str:
    """
    Compute geohash for coordinates.
    
    Args:
        lat: Latitude
        lon: Longitude
        precision: Geohash precision (6 = ~1.2km x 0.6km)
        
    Returns:
        Geohash string
    """
    _validate_lat_lon(lat, lon)
    precision = max(1, min(int(precision), 12))
    return pgh.encode(lat, lon, precision=precision)


def geohash_to_bbox(geohash: str) -> Tuple[float, float, float, float]:
    """
    Convert geohash to bounding box.
    
    Args:
        geohash: Geohash string
        
    Returns:
        Tuple of (min_lat, min_lon, max_lat, max_lon)
    """
    return pgh.decode_exactly(geohash)


def invalidate_expired_cache(session: Session) -> int:
    """
    Delete expired analysis cache entries.
    
    Args:
        session: SQLAlchemy session
        
    Returns:
        Number of entries deleted
    """
    stmt = delete(AnalysisCache).where(
        AnalysisCache.expires_at < datetime.utcnow()
    )
    
    result = session.execute(stmt)
    deleted_count = result.rowcount
    
    # TODO: Guard delete scope with lock timeout to avoid blocking active read/write workloads.
    logger.info(f"Invalidated {deleted_count} expired cache entries")
    return deleted_count


__all__ = [
    # Building queries
    "get_buildings_in_radius",
    "get_buildings_in_radius_async",
    "get_buildings_in_bbox",
    "get_buildings_in_bbox_async",
    "insert_buildings_batch",
    "insert_buildings_batch_async",
    # Terrain queries
    "get_terrain_tile",
    "get_terrain_tile_async",
    # Analysis cache queries
    "get_cached_analysis",
    "get_cached_analysis_async",
    "cache_analysis_result",
    "cache_analysis_result_async",
    # TLE cache queries
    "get_cached_tles",
    "get_cached_tles_async",
    "cache_tles",
    "cache_tles_async",
    # Utilities
    "compute_geohash",
    "geohash_to_bbox",
    "invalidate_expired_cache",
]
