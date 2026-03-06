# Copyright (c) 2024 LinkSpot Project
# BSD 3-Clause License
# SPDX-License-Identifier: BSD-3-Clause
#
# data_pipeline.py - Main building and terrain data pipeline
# Ingests 3D building footprints with heights and terrain elevation data

"""
LinkSpot Data Pipeline Module

This module provides the main pipeline for ingesting 3D building footprints
and terrain elevation data from multiple sources:
- Building data: Overture Maps Foundation (primary), OSM Overpass (fallback)
- Terrain data: Copernicus GLO-30 Digital Surface Model

All coordinate systems use WGS84 (EPSG:4326) for input/output with
internal conversion to local ENU Cartesian frames as needed.
"""

import logging
import time
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Polygon, Point, box, mapping
from shapely.ops import transform as shapely_transform
import pyproj
from pyproj import Transformer, CRS

# Redis and caching
import redis
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

# Database
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# Internal clients
from overture_client import OvertureMapsClient
from terrain_client import CopernicusTerrainClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class BuildingData:
    """Data class for building information."""
    geometry: Polygon
    height: Optional[float]
    source: str
    building_id: Optional[str] = None
    confidence: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None


@dataclass
class TerrainData:
    """Data class for terrain elevation information."""
    elevation: float
    source: str
    resolution_m: float
    lat: float
    lon: float


class GeohashEncoder:
    """Geohash encoding for cache keys."""
    
    # Base32 character set for geohash
    BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    
    @staticmethod
    def encode(lat: float, lon: float, precision: int = 6) -> str:
        """
        Encode latitude/longitude to geohash string.
        
        Precision 6 gives ~1.2km x 0.6km cells.
        
        Args:
            lat: Latitude in degrees (-90 to 90)
            lon: Longitude in degrees (-180 to 180)
            precision: Number of characters in geohash (default 6)
            
        Returns:
            Geohash string
        """
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude must be in range [-90, 90], got {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude must be in range [-180, 180], got {lon}")
            
        lat_range = [-90.0, 90.0]
        lon_range = [-180.0, 180.0]
        
        geohash = []
        bits = 0
        bits_total = 0
        ch = 0
        even = True
        
        while len(geohash) < precision:
            if even:
                # Divide longitude range
                mid = (lon_range[0] + lon_range[1]) / 2
                if lon >= mid:
                    ch |= (1 << (4 - bits))
                    lon_range[0] = mid
                else:
                    lon_range[1] = mid
            else:
                # Divide latitude range
                mid = (lat_range[0] + lat_range[1]) / 2
                if lat >= mid:
                    ch |= (1 << (4 - bits))
                    lat_range[0] = mid
                else:
                    lat_range[1] = mid
                    
            even = not even
            bits += 1
            
            if bits == 5:
                geohash.append(GeohashEncoder.BASE32[ch])
                bits = 0
                ch = 0
                
        return ''.join(geohash)
    
    @staticmethod
    def decode(geohash: str) -> Tuple[float, float]:
        """
        Decode geohash to approximate center latitude/longitude.
        
        Args:
            geohash: Geohash string to decode
            
        Returns:
            Tuple of (latitude, longitude) for cell center
        """
        lat_range = [-90.0, 90.0]
        lon_range = [-180.0, 180.0]
        even = True
        
        for char in geohash:
            cd = GeohashEncoder.BASE32.index(char)
            for mask in [16, 8, 4, 2, 1]:
                if even:
                    # Refine longitude
                    mid = (lon_range[0] + lon_range[1]) / 2
                    if cd & mask:
                        lon_range[0] = mid
                    else:
                        lon_range[1] = mid
                else:
                    # Refine latitude
                    mid = (lat_range[0] + lat_range[1]) / 2
                    if cd & mask:
                        lat_range[0] = mid
                    else:
                        lat_range[1] = mid
                even = not even
                
        lat = (lat_range[0] + lat_range[1]) / 2
        lon = (lon_range[0] + lon_range[1]) / 2
        return lat, lon


class CoordinateConverter:
    """Convert between WGS84 and local ENU Cartesian coordinate systems."""
    
    def __init__(self, origin_lat: float, origin_lon: float, origin_height: float = 0.0):
        """
        Initialize coordinate converter with ENU origin.
        
        Args:
            origin_lat: Origin latitude in degrees
            origin_lon: Origin longitude in degrees
            origin_height: Origin height above ellipsoid in meters
        """
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.origin_height = origin_height
        
        # Create ENU projection centered at origin
        # ENU: East-North-Up local tangent plane
        self.enu_crs = self._create_enu_crs()
        self.wgs84_crs = CRS.from_epsg(4326)
        
        # Create transformers
        self.wgs84_to_enu = Transformer.from_crs(
            self.wgs84_crs, self.enu_crs, always_xy=True
        )
        self.enu_to_wgs84 = Transformer.from_crs(
            self.enu_crs, self.wgs84_crs, always_xy=True
        )
        
    def _create_enu_crs(self) -> CRS:
        """Create a local ENU CRS centered at the origin point."""
        # Use PROJ string for topocentric ENU
        # +proj=topocentric with origin coordinates
        proj_string = (
            f"+proj=topocentric +ellps=WGS84 "
            f"+lon_0={self.origin_lon} "
            f"+lat_0={self.origin_lat} "
            f"+h_0={self.origin_height}"
        )
        return CRS.from_proj4(proj_string)
    
    def wgs84_to_enu_coords(self, lon: float, lat: float, height: float = 0.0) -> Tuple[float, float, float]:
        """
        Convert WGS84 coordinates to ENU.
        
        Args:
            lon: Longitude in degrees
            lat: Latitude in degrees
            height: Height above ellipsoid in meters
            
        Returns:
            Tuple of (east, north, up) in meters
        """
        try:
            east, north, up = self.wgs84_to_enu.transform(lon, lat, height)
            return east, north, up
        except Exception as e:
            logger.warning(f"Error in WGS84 to ENU conversion: {e}")
            # Fallback to approximate conversion
            return self._approximate_wgs84_to_enu(lon, lat, height)
    
    def _approximate_wgs84_to_enu(self, lon: float, lat: float, height: float = 0.0) -> Tuple[float, float, float]:
        """
        Approximate WGS84 to ENU conversion using local tangent plane.
        
        This is a simplified conversion that works well for small distances.
        """
        # Convert degrees to radians
        lat_rad = np.radians(lat)
        lon_rad = np.radians(lon)
        origin_lat_rad = np.radians(self.origin_lat)
        origin_lon_rad = np.radians(self.origin_lon)
        
        # Earth's radius at latitude
        R = 6371000.0  # Earth's mean radius in meters
        
        # Calculate differences
        dlat = lat_rad - origin_lat_rad
        dlon = lon_rad - origin_lon_rad
        
        # North and East components
        north = R * dlat
        east = R * np.cos(origin_lat_rad) * dlon
        up = height - self.origin_height
        
        return east, north, up
    
    def enu_to_wgs84_coords(self, east: float, north: float, up: float = 0.0) -> Tuple[float, float, float]:
        """
        Convert ENU coordinates to WGS84.
        
        Args:
            east: Easting in meters
            north: Northing in meters
            up: Up component in meters
            
        Returns:
            Tuple of (longitude, latitude, height) in degrees and meters
        """
        try:
            lon, lat, height = self.enu_to_wgs84.transform(east, north, up)
            return lon, lat, height
        except Exception as e:
            logger.warning(f"Error in ENU to WGS84 conversion: {e}")
            # Fallback to approximate conversion
            return self._approximate_enu_to_wgs84(east, north, up)
    
    def _approximate_enu_to_wgs84(self, east: float, north: float, up: float = 0.0) -> Tuple[float, float, float]:
        """Approximate ENU to WGS84 conversion."""
        R = 6371000.0
        origin_lat_rad = np.radians(self.origin_lat)
        
        dlat = north / R
        dlon = east / (R * np.cos(origin_lat_rad))
        
        lat = self.origin_lat + np.degrees(dlat)
        lon = self.origin_lon + np.degrees(dlon)
        height = self.origin_height + up
        
        return lon, lat, height


class BuildingHeightEstimator:
    """Estimate building heights when not available from data sources."""
    
    # Default height assumptions by building type (meters)
    DEFAULT_HEIGHTS = {
        'residential': 9.0,      # ~3 stories
        'apartments': 15.0,      # ~5 stories
        'commercial': 12.0,      # ~4 stories
        'retail': 6.0,           # ~2 stories
        'office': 15.0,          # ~5 stories
        'industrial': 12.0,      # ~4 stories
        'warehouse': 8.0,        # ~2-3 stories
        'school': 12.0,          # ~4 stories
        'hospital': 18.0,        # ~6 stories
        'church': 15.0,          # ~5 stories
        'garage': 4.0,           # ~1-2 stories
        'shed': 3.0,             # ~1 story
        'roof': 6.0,             # Default roof height
        'yes': 9.0,              # Generic building
    }
    
    # Story height assumptions (meters per story)
    STORY_HEIGHT = 3.0
    
    def __init__(self):
        """Initialize height estimator."""
        self.stats = {
            'estimated_count': 0,
            'from_levels_count': 0,
            'from_osm_count': 0,
            'default_count': 0
        }
    
    def estimate_height(self, building_row: pd.Series) -> Tuple[float, str, float]:
        """
        Estimate building height from available data.
        
        Args:
            building_row: Pandas Series with building attributes
            
        Returns:
            Tuple of (height_meters, method, confidence)
        """
        # Priority 1: Direct height tag
        if 'height' in building_row and pd.notna(building_row['height']):
            height = self._parse_height(building_row['height'])
            if height is not None:
                self.stats['from_osm_count'] += 1
                return height, 'osm_height_tag', 0.9
        
        # Priority 2: Building levels
        if 'building:levels' in building_row and pd.notna(building_row['building:levels']):
            levels = self._parse_levels(building_row['building:levels'])
            if levels is not None:
                height = levels * self.STORY_HEIGHT
                self.stats['from_levels_count'] += 1
                return height, 'building_levels', 0.7
        
        # Priority 3: Building type default
        building_type = building_row.get('building', 'yes')
        if isinstance(building_type, str):
            building_type = building_type.lower()
            if building_type in self.DEFAULT_HEIGHTS:
                height = self.DEFAULT_HEIGHTS[building_type]
                self.stats['default_count'] += 1
                return height, f'default_{building_type}', 0.5
        
        # Fallback: generic default
        self.stats['default_count'] += 1
        return self.DEFAULT_HEIGHTS['yes'], 'default_generic', 0.3
    
    def _parse_height(self, height_value: Any) -> Optional[float]:
        """Parse height value from various formats."""
        if pd.isna(height_value):
            return None
            
        if isinstance(height_value, (int, float)):
            return float(height_value)
        
        if isinstance(height_value, str):
            # Remove units and extract number
            height_str = height_value.strip().lower()
            height_str = height_str.replace('m', '').replace('meters', '')
            height_str = height_str.replace("'", '').replace('ft', '')
            height_str = height_str.replace('feet', '')
            
            # Handle ranges (take average)
            if '-' in height_str:
                parts = height_str.split('-')
                try:
                    return (float(parts[0]) + float(parts[1])) / 2
                except (ValueError, IndexError):
                    pass
            
            try:
                return float(height_str)
            except ValueError:
                pass
        
        return None
    
    def _parse_levels(self, levels_value: Any) -> Optional[int]:
        """Parse building levels from various formats."""
        if pd.isna(levels_value):
            return None
            
        if isinstance(levels_value, (int, float)):
            return int(levels_value)
        
        if isinstance(levels_value, str):
            levels_str = levels_value.strip()
            
            # Handle ranges (take maximum for safety)
            if '-' in levels_str:
                parts = levels_str.split('-')
                try:
                    return int(parts[1])
                except (ValueError, IndexError):
                    try:
                        return int(parts[0])
                    except ValueError:
                        pass
            
            try:
                return int(levels_str)
            except ValueError:
                pass
        
        return None
    
    def get_stats(self) -> Dict[str, int]:
        """Get estimation statistics."""
        return self.stats.copy()


class LinkSpotDataPipeline:
    """
    Main data pipeline for building and terrain data ingestion.
    
    This class provides a unified interface for querying 3D building footprints
    and terrain elevation data with caching and fallback mechanisms.
    """
    
    # Cache TTL in seconds (24 hours)
    CACHE_TTL = 86400
    
    # Cache key prefix
    CACHE_PREFIX = "linkspot:buildings:"
    
    # Performance targets
    HOT_CACHE_TARGET_MS = 500
    COLD_QUERY_TARGET_MS = 3000
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        postgis_conn_string: Optional[str] = None,
        enable_overture: bool = True,
        enable_osm_fallback: bool = True,
        enable_terrain: bool = True
    ):
        """
        Initialize the data pipeline.
        
        Args:
            redis_client: Redis client for hot caching (optional)
            postgis_conn_string: PostGIS connection string (optional)
            enable_overture: Enable Overture Maps as primary source
            enable_osm_fallback: Enable OSM Overpass as fallback
            enable_terrain: Enable terrain data queries
        """
        self.redis_client = redis_client
        self.postgis_conn_string = postgis_conn_string
        self.enable_overture = enable_overture
        self.enable_osm_fallback = enable_osm_fallback
        self.enable_terrain = enable_terrain
        
        # Initialize clients
        self.overture_client: Optional[OvertureMapsClient] = None
        self.terrain_client: Optional[CopernicusTerrainClient] = None
        self.height_estimator = BuildingHeightEstimator()
        self.geohash_encoder = GeohashEncoder()
        
        # Database engine
        self.db_engine = None
        if postgis_conn_string:
            try:
                self.db_engine = create_engine(
                    postgis_conn_string,
                    poolclass=NullPool,
                    connect_args={'connect_timeout': 10}
                )
                # TODO: Move DB client tuning (pooling, timeout, NullPool choice) into settings so
                #      profiles can tune behavior independently.
                logger.info("PostGIS database engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize PostGIS engine: {e}")
        
        # Initialize Overture client
        if enable_overture:
            try:
                self.overture_client = OvertureMapsClient()
                logger.info("Overture Maps client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Overture client: {e}")
        
        # Initialize terrain client
        if enable_terrain:
            try:
                self.terrain_client = CopernicusTerrainClient()
                logger.info("Copernicus terrain client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize terrain client: {e}")
        
        # Query statistics
        self.stats = {
            'total_queries': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'overture_queries': 0,
            'osm_fallback_queries': 0,
            'db_queries': 0,
            'errors': 0
        }
    
    def _get_cache_key(self, geohash: str) -> str:
        """Generate Redis cache key for geohash."""
        return f"{self.CACHE_PREFIX}{geohash}"
    
    def _bbox_from_radius(self, lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
        """
        Calculate bounding box from center point and radius.
        
        Args:
            lat: Center latitude
            lon: Center longitude
            radius_m: Radius in meters
            
        Returns:
            Tuple of (min_lon, min_lat, max_lon, max_lat)
        """
        if radius_m <= 0:
            raise ValueError(f"Radius must be positive, got {radius_m}")
        # Approximate degrees per meter (varies with latitude)
        lat = float(np.clip(lat, -89.999, 89.999))
        lon = ((float(lon) + 180.0) % 360.0) - 180.0
        meters_per_degree_lat = 111320.0
        meters_per_degree_lon = max(1e-6, meters_per_degree_lat * np.cos(np.radians(lat)))
        
        delta_lat = radius_m / meters_per_degree_lat
        delta_lon = radius_m / meters_per_degree_lon

        min_lat = float(np.clip(lat - delta_lat, -90.0, 90.0))
        max_lat = float(np.clip(lat + delta_lat, -90.0, 90.0))
        min_lon = lon - delta_lon
        max_lon = lon + delta_lon

        # Antimeridian crossing: use full-longitude bbox fallback for safe external queries.
        if min_lon < -180.0 or max_lon > 180.0:
            return (-180.0, min_lat, 180.0, max_lat)

        return (min_lon, min_lat, max_lon, max_lat)
    
    def _filter_by_radius(
        self,
        gdf: gpd.GeoDataFrame,
        center_lat: float,
        center_lon: float,
        radius_m: float
    ) -> gpd.GeoDataFrame:
        """Filter GeoDataFrame to buildings within radius."""
        if gdf.empty:
            return gdf
        
        center = Point(center_lon, center_lat)
        
        # Calculate distance for each geometry
        # Use centroid for distance calculation
        gdf = gdf.copy()
        centroids = gdf.geometry.centroid
        lat1 = np.radians(float(center_lat))
        lon1 = np.radians(float(center_lon))
        lat2 = np.radians(centroids.y.to_numpy())
        lon2 = np.radians(centroids.x.to_numpy())
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
        gdf['distance_m'] = 6371000.0 * c
        
        # Filter by radius
        filtered = gdf[gdf['distance_m'] <= radius_m].copy()
        
        return filtered.drop(columns=['distance_m'])
    
    def get_buildings_in_radius(
        self,
        lat: float,
        lon: float,
        radius_m: float = 500
    ) -> gpd.GeoDataFrame:
        """
        Get buildings within radius of a point.
        
        This is the main query method that implements the full fallback chain:
        1. Check Redis hot cache
        2. Query PostGIS warm store
        3. Query Overture Maps S3
        4. Fallback to OSM Overpass API
        
        Args:
            lat: Query latitude
            lon: Query longitude
            radius_m: Query radius in meters (default 500)
            
        Returns:
            GeoDataFrame with building footprints and heights
        """
        start_time = time.time()
        self.stats['total_queries'] += 1
        
        logger.info(f"Querying buildings at ({lat}, {lon}) with radius {radius_m}m")
        
        # Calculate geohash for cache key
        geohash = self.geohash_encoder.encode(lat, lon, precision=6)
        
        # Step 1: Check Redis hot cache
        cached_buildings = self.get_cached_buildings(geohash)
        if cached_buildings is not None and not cached_buildings.empty:
            logger.info("Cache hit - returning cached buildings")
            self.stats['cache_hits'] += 1
            filtered = self._filter_by_radius(cached_buildings, lat, lon, radius_m)
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"Hot cache query completed in {elapsed_ms:.1f}ms")
            return filtered
        
        self.stats['cache_misses'] += 1
        
        # Step 2: Query PostGIS warm store
        if self.db_engine is not None:
            try:
                buildings = self._query_postgis_buildings(lat, lon, radius_m)
                if buildings is not None and not buildings.empty:
                    logger.info(f"Retrieved {len(buildings)} buildings from PostGIS")
                    self.stats['db_queries'] += 1
                    # Cache results
                    self.cache_buildings(geohash, buildings)
                    return buildings
            except Exception as e:
                logger.warning(f"PostGIS query failed: {e}")
        
        # Step 3: Query Overture Maps
        if self.enable_overture and self.overture_client is not None:
            try:
                bbox = self._bbox_from_radius(lat, lon, radius_m * 1.5)  # Slightly larger for cache
                buildings = self.fetch_overture_buildings(bbox)
                if buildings is not None and not buildings.empty:
                    logger.info(f"Retrieved {len(buildings)} buildings from Overture Maps")
                    self.stats['overture_queries'] += 1
                    # Cache and return
                    # TODO: Cache query provenance (source + bbox) so stale/partial results can be surfaced in telemetry.
                    self.cache_buildings(geohash, buildings)
                    filtered = self._filter_by_radius(buildings, lat, lon, radius_m)
                    return filtered
            except Exception as e:
                logger.warning(f"Overture query failed: {e}")
        
        # Step 4: Fallback to OSM Overpass
        if self.enable_osm_fallback:
            try:
                bbox = self._bbox_from_radius(lat, lon, radius_m * 1.5)
                buildings = self.fetch_osm_buildings_fallback(bbox)
                if buildings is not None and not buildings.empty:
                    logger.info(f"Retrieved {len(buildings)} buildings from OSM Overpass")
                    self.stats['osm_fallback_queries'] += 1
                    # Cache and return
                    self.cache_buildings(geohash, buildings)
                    filtered = self._filter_by_radius(buildings, lat, lon, radius_m)
                    return filtered
            except Exception as e:
                logger.warning(f"OSM fallback query failed: {e}")
        
        # Return empty GeoDataFrame if all sources failed
        logger.warning(
            "All building data sources failed for location (%.4f, %.4f) radius=%dm. "
            "Analysis will proceed with zero obstruction.",
            lat,
            lon,
            int(radius_m),
        )
        self.stats['errors'] += 1
        return gpd.GeoDataFrame(
            columns=['geometry', 'height', 'source'],
            geometry=[], crs='EPSG:4326'
        )
    
    def _query_postgis_buildings(
        self,
        lat: float,
        lon: float,
        radius_m: float
    ) -> Optional[gpd.GeoDataFrame]:
        """Query buildings from PostGIS database."""
        if self.db_engine is None:
            return None
        
        query = text("""
            SELECT 
                ST_AsGeoJSON(geometry) as geom_geojson,
                height,
                building_type,
                source,
                building_id
            FROM buildings
            WHERE ST_DWithin(
                geometry::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
        """)
        
        try:
            with self.db_engine.connect() as conn:
                result = conn.execute(query, {
                    'lat': lat,
                    'lon': lon,
                    'radius': radius_m
                })
                
                rows = []
                for row in result:
                    geom = json.loads(row.geom_geojson)
                    if not geom or 'coordinates' not in geom:
                        logger.debug("Skipping PostGIS row with malformed geometry payload")
                        # TODO: Track malformed geometry events separately from query failures.
                        continue
                    rows.append({
                        'geometry': Polygon(geom['coordinates'][0]),
                        'height': row.height,
                        'building_type': row.building_type,
                        'source': row.source,
                        'building_id': row.building_id
                    })
                
                if rows:
                    return gpd.GeoDataFrame(rows, crs='EPSG:4326')
                return None
                
        except Exception as e:
            logger.warning(f"PostGIS query error: {e}")
            return None
    
    def fetch_overture_buildings(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[gpd.GeoDataFrame]:
        """
        Fetch buildings from Overture Maps S3.
        
        Args:
            bbox: Tuple of (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            GeoDataFrame with building data
        """
        if self.overture_client is None:
            logger.warning("Overture client not initialized")
            return None
        
        try:
            gdf = self.overture_client.query_buildings(bbox)
            
            if gdf is not None and not gdf.empty:
                # Add height column if missing
                if 'height' not in gdf.columns:
                    gdf['height'] = None
                
                # Estimate heights where missing
                for idx, row in gdf.iterrows():
                    if pd.isna(row.get('height')):
                        height, method, confidence = self.height_estimator.estimate_height(row)
                        gdf.at[idx, 'height'] = height
                        gdf.at[idx, 'height_method'] = method
                        gdf.at[idx, 'height_confidence'] = confidence
                
                # Ensure source column
                gdf['source'] = 'overture_maps'
                
                return gdf
            
            return gdf
            
        except Exception as e:
            logger.error(f"Overture fetch error: {e}")
            # TODO: Distinguish timeout/transient vs permanent Overture failures before surfacing status.
            return None
    
    def fetch_osm_buildings_fallback(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[gpd.GeoDataFrame]:
        """
        Fetch buildings from OSM Overpass API as fallback.
        
        Args:
            bbox: Tuple of (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            GeoDataFrame with building data
        """
        import requests
        import time
        
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Overpass API query for buildings
        overpass_query = f"""
        [out:json][timeout:60];
        (
          way["building"]({min_lat},{min_lon},{max_lat},{max_lon});
          relation["building"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out body;
        >;
        out skel qt;
        """
        
        # Rate limiting - max ~1 request per 2 seconds with jitter.
        time.sleep(1.8 + np.random.uniform(0.0, 0.4))
        
        try:
            logger.info("Querying OSM Overpass API")
            overpass_hosts = [
                'https://overpass-api.de/api/interpreter',
                'https://overpass.kumi.systems/api/interpreter',
                'https://overpass.openstreetmap.fr/api/interpreter',
            ]
            data = None
            last_error = None
            for host in overpass_hosts:
                try:
                    response = requests.post(
                        host,
                        data={'data': overpass_query},
                        timeout=30,
                    )
                    response.raise_for_status()
                    data = response.json()
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning("Overpass host failed (%s): %s", host, exc)
            if data is None:
                raise requests.exceptions.RequestException(str(last_error))
            
            # Parse OSM data
            nodes = {}
            ways = []
            
            for element in data['elements']:
                if element['type'] == 'node':
                    nodes[element['id']] = (element['lon'], element['lat'])
                elif element['type'] == 'way':
                    ways.append(element)
            
            # Convert to GeoDataFrame
            buildings = []
            for way in ways:
                if 'tags' not in way:
                    continue
                
                tags = way['tags']
                node_ids = way.get('nodes', [])
                
                # Get coordinates
                coords = []
                for node_id in node_ids:
                    if node_id in nodes:
                        coords.append(nodes[node_id])
                
                if len(coords) < 3:
                    continue
                
                # Create polygon
                try:
                    polygon = Polygon(coords)
                    
                    # Extract attributes
                    building_data = {
                        'geometry': polygon,
                        'building': tags.get('building', 'yes'),
                        'height': tags.get('height'),
                        'building:levels': tags.get('building:levels'),
                        'name': tags.get('name'),
                        'osm_id': way['id']
                    }
                    buildings.append(building_data)
                except Exception as e:
                    logger.debug(f"Failed to create polygon: {e}")
                    continue
            
            if buildings:
                gdf = gpd.GeoDataFrame(buildings, crs='EPSG:4326')
                
                # Estimate heights
                for idx, row in gdf.iterrows():
                    height, method, confidence = self.height_estimator.estimate_height(row)
                    gdf.at[idx, 'height'] = height
                    gdf.at[idx, 'height_method'] = method
                    gdf.at[idx, 'height_confidence'] = confidence
                
                gdf['source'] = 'osm_overpass'
                
                return gdf
            
            return gpd.GeoDataFrame(columns=['geometry', 'height', 'source'], crs='EPSG:4326')
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Overpass API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"OSM parsing error: {e}")
            return None
    
    def get_terrain_elevation(self, lat: float, lon: float) -> Optional[TerrainData]:
        """
        Get terrain elevation at a single point.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            TerrainData with elevation information
        """
        if self.terrain_client is None:
            logger.warning("Terrain client not initialized")
            return None
        
        try:
            elevation = self.terrain_client.get_elevation(lat, lon)
            
            return TerrainData(
                elevation=elevation,
                source='copernicus_glo30',
                resolution_m=30.0,
                lat=lat,
                lon=lon
            )
            
        except Exception as e:
            logger.error(f"Terrain elevation query failed: {e}")
            return None
    
    def get_terrain_patch(
        self,
        lat: float,
        lon: float,
        radius_m: float
    ) -> Optional[np.ndarray]:
        """
        Get terrain elevation patch for an area.
        
        Args:
            lat: Center latitude
            lon: Center longitude
            radius_m: Radius in meters
            
        Returns:
            NumPy array of elevation values
        """
        if self.terrain_client is None:
            logger.warning("Terrain client not initialized")
            return None
        
        try:
            bbox = self._bbox_from_radius(lat, lon, radius_m)
            # TODO: Cap terrain radius and sampling density to avoid excessive patch extraction on broad requests.
            return self.terrain_client.get_elevation_patch(bbox)
            
        except Exception as e:
            logger.error(f"Terrain patch query failed: {e}")
            return None
    
    def cache_buildings(
        self,
        geohash: str,
        buildings_data: gpd.GeoDataFrame
    ) -> bool:
        """
        Cache building data in Redis with TTL.
        
        Args:
            geohash: Geohash string for cache key
            buildings_data: GeoDataFrame to cache
            
        Returns:
            True if caching succeeded
        """
        if self.redis_client is None:
            logger.debug("Redis not configured, skipping cache")
            return False
        
        try:
            cache_key = self._get_cache_key(geohash)
            
            # Convert GeoDataFrame to GeoJSON for storage
            geojson_str = buildings_data.to_json()
            if len(geojson_str) > 5_000_000:
                logger.warning("Skipping cache write for geohash %s: payload too large", geohash)
                return False
            
            # Store with TTL
            self.redis_client.setex(
                cache_key,
                self.CACHE_TTL,
                geojson_str
            )
            
            logger.debug(f"Cached {len(buildings_data)} buildings for geohash {geohash}")
            return True
            
        except RedisConnectionError as e:
            logger.warning(f"Redis connection error during cache: {e}")
            return False
        except Exception as e:
            logger.warning(f"Cache operation failed: {e}")
            return False
    
    def get_cached_buildings(self, geohash: str) -> Optional[gpd.GeoDataFrame]:
        """
        Retrieve building data from Redis cache.
        
        Args:
            geohash: Geohash string for cache key
            
        Returns:
            GeoDataFrame if cache hit, None otherwise
        """
        if self.redis_client is None:
            return None
        
        try:
            cache_key = self._get_cache_key(geohash)
            cached_data = self.redis_client.get(cache_key)
            
            if cached_data is None:
                return None
            
            # Parse GeoJSON back to GeoDataFrame
            import io
            decoded = cached_data.decode('utf-8')
            payload = json.loads(decoded)
            if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
                logger.warning("Invalid cached payload for geohash %s", geohash)
                return None
            gdf = gpd.read_file(io.StringIO(decoded))
            
            logger.debug(f"Cache hit for geohash {geohash}")
            return gdf
            
        except RedisConnectionError as e:
            logger.warning(f"Redis connection error during cache read: {e}")
            return None
        except Exception as e:
            logger.warning(f"Cache read failed: {e}")
            return None
    
    def estimate_building_height(self, building: pd.Series) -> Tuple[float, str, float]:
        """
        Estimate building height using the height estimator.
        
        Args:
            building: Pandas Series with building attributes
            
        Returns:
            Tuple of (height_meters, method, confidence)
        """
        return self.height_estimator.estimate_height(building)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline query statistics."""
        return {
            **self.stats,
            'height_estimation': self.height_estimator.get_stats()
        }
    
    def clear_cache(self) -> bool:
        """Clear all building data from Redis cache."""
        if self.redis_client is None:
            return False
        
        try:
            pattern = f"{self.CACHE_PREFIX}*"
            deleted = 0
            for key in self.redis_client.scan_iter(match=pattern, count=500):
                self.redis_client.delete(key)
                deleted += 1
            logger.info(f"Cleared {deleted} cached entries")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False


# Convenience function for quick queries
def query_buildings(
    lat: float,
    lon: float,
    radius_m: float = 500,
    redis_client: Optional[redis.Redis] = None,
    postgis_conn_string: Optional[str] = None
) -> gpd.GeoDataFrame:
    """
    Quick query function for buildings without initializing pipeline.
    
    Args:
        lat: Query latitude
        lon: Query longitude
        radius_m: Query radius in meters
        redis_client: Optional Redis client
        postgis_conn_string: Optional PostGIS connection string
        
    Returns:
        GeoDataFrame with building data
    """
    pipeline = LinkSpotDataPipeline(
        redis_client=redis_client,
        postgis_conn_string=postgis_conn_string
    )
    return pipeline.get_buildings_in_radius(lat, lon, radius_m)


if __name__ == '__main__':
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Initialize pipeline (without Redis/PostGIS for demo)
    pipeline = LinkSpotDataPipeline()
    
    # Query buildings near Times Square
    buildings = pipeline.get_buildings_in_radius(40.7580, -73.9855, radius_m=500)
    
    print(f"Found {len(buildings)} buildings")
    if not buildings.empty:
        print(buildings.head())
    
    # Get terrain elevation
    terrain = pipeline.get_terrain_elevation(40.7580, -73.9855)
    if terrain:
        print(f"Elevation: {terrain.elevation}m")
