# Copyright (c) 2024 LinkSpot Project
# BSD 3-Clause License
# SPDX-License-Identifier: BSD-3-Clause
#
# overture_client.py - Overture Maps Foundation S3 client
# Provides efficient GeoParquet streaming from Overture Maps S3 buckets

"""
Overture Maps Foundation Client Module

This module provides a client for querying building data from the
Overture Maps Foundation S3-hosted GeoParquet datasets.

Data Attribution:
- Source: Overture Maps Foundation (https://overturemaps.org/)
- License: ODbL (Open Database License)
- Data format: GeoParquet on AWS S3

The ODbL requires:
- Attribution to Overture Maps Foundation
- Share-alike for derivative databases
- Clear indication of changes made
"""

import logging
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path
import io

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Polygon, box
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.dataset as ds
import pyarrow.fs as fs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OvertureMapsClient:
    """
    Client for querying Overture Maps Foundation building data.
    
    This client provides efficient access to the Overture Maps building
    footprints dataset stored as GeoParquet files on AWS S3.
    
    The dataset is partitioned by theme and type for efficient querying.
    """
    
    # Overture Maps S3 bucket configuration
    S3_BUCKET = "overturemaps-us-west-2"
    S3_PREFIX = "release/2024-10-23.0/theme=buildings"
    
    # ODbL attribution string
    ATTRIBUTION = "© Overture Maps Foundation, ODbL"
    
    # Dataset version
    DATASET_VERSION = "2024-10-23.0"
    
    def __init__(self, s3_bucket: Optional[str] = None, s3_prefix: Optional[str] = None):
        """
        Initialize the Overture Maps client.
        
        Args:
            s3_bucket: S3 bucket name (default: overturemaps-us-west-2)
            s3_prefix: S3 prefix path (default: release/2024-10-23.0/theme=buildings)
        """
        self.s3_bucket = s3_bucket or self.S3_BUCKET
        self.s3_prefix = s3_prefix or self.S3_PREFIX
        
        # Initialize S3 filesystem
        self.s3_fs = fs.S3FileSystem(
            region="us-west-2",
            anonymous=True  # Overture data is public
        )
        
        # Cache for dataset structure
        self._dataset: Optional[ds.Dataset] = None
        self._schema: Optional[pa.Schema] = None
        
        logger.info(f"Overture Maps client initialized (bucket: {self.s3_bucket})")
    
    def _get_dataset(self) -> ds.Dataset:
        """
        Get or create the PyArrow dataset for buildings.
        
        Returns:
            PyArrow Dataset object
        """
        if self._dataset is None:
            s3_path = f"{self.s3_bucket}/{self.s3_prefix}"
            logger.debug(f"Loading dataset from {s3_path}")
            
            try:
                self._dataset = ds.dataset(
                    s3_path,
                    filesystem=self.s3_fs,
                    format="parquet"
                )
                self._schema = self._dataset.schema
                logger.info(f"Dataset loaded with {self._dataset.count_rows():,} rows")
            except Exception as e:
                logger.error(f"Failed to load dataset: {e}")
                raise
        
        return self._dataset
    
    def _bbox_to_filter(self, bbox: Tuple[float, float, float, float]) -> ds.Expression:
        """
        Convert bounding box to PyArrow filter expression.
        
        Args:
            bbox: Tuple of (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            PyArrow filter expression
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Build filter for bbox intersection
        # Overture data has bbox columns: bbox.minX, bbox.minY, bbox.maxX, bbox.maxY
        filter_expr = (
            (ds.field("bbox", "minX") <= max_lon) &
            (ds.field("bbox", "maxX") >= min_lon) &
            (ds.field("bbox", "minY") <= max_lat) &
            (ds.field("bbox", "maxY") >= min_lat)
        )
        
        return filter_expr
    
    def query_buildings(
        self,
        bbox_wgs84: Tuple[float, float, float, float],
        columns: Optional[List[str]] = None
    ) -> Optional[gpd.GeoDataFrame]:
        """
        Query buildings within a bounding box.
        
        Args:
            bbox_wgs84: Tuple of (min_lon, min_lat, max_lon, max_lat) in WGS84
            columns: Optional list of columns to retrieve (None for all)
            
        Returns:
            GeoDataFrame with building data, or None if query fails
        """
        min_lon, min_lat, max_lon, max_lat = bbox_wgs84
        
        logger.info(
            f"Querying Overture buildings in bbox: "
            f"({min_lon:.4f}, {min_lat:.4f}, {max_lon:.4f}, {max_lat:.4f})"
        )
        
        try:
            dataset = self._get_dataset()
            
            # Build filter
            filter_expr = self._bbox_to_filter(bbox_wgs84)
            
            # Default columns if not specified
            if columns is None:
                columns = [
                    "id",
                    "geometry",
                    "height",
                    "num_floors",
                    "class",
                    "source",
                    "confidence",
                    "bbox"
                ]
            
            # Scan dataset with filter
            scanner = dataset.scanner(
                columns=columns,
                filter=filter_expr
            )
            
            # Read to table
            table = scanner.to_table()
            
            if table.num_rows == 0:
                logger.info("No buildings found in query area")
                return gpd.GeoDataFrame(columns=['geometry', 'height'], crs='EPSG:4326')
            
            logger.info(f"Retrieved {table.num_rows:,} buildings from Overture")
            
            # Convert to GeoDataFrame
            gdf = self._table_to_geodataframe(table)
            
            # Add attribution
            gdf['data_attribution'] = self.ATTRIBUTION
            gdf['data_version'] = self.DATASET_VERSION
            
            return gdf
            
        except Exception as e:
            logger.error(f"Overture query failed: {e}")
            return None
    
    def _table_to_geodataframe(self, table: pa.Table) -> gpd.GeoDataFrame:
        """
        Convert PyArrow table to GeoDataFrame.
        
        Args:
            table: PyArrow table with geometry column
            
        Returns:
            GeoDataFrame with proper geometry
        """
        # Convert to pandas first
        df = table.to_pandas()
        
        # Process geometry column (WKB format in Overture)
        if 'geometry' in df.columns:
            import shapely.wkb
            
            # Decode WKB to shapely geometries
            geometries = []
            for geom_bytes in df['geometry']:
                if geom_bytes is not None:
                    try:
                        geom = shapely.wkb.loads(geom_bytes)
                        geometries.append(geom)
                    except Exception as e:
                        logger.debug(f"Failed to parse geometry: {e}")
                        geometries.append(None)
                else:
                    geometries.append(None)
                # TODO: Add geometry validation for non-polygon or malformed WKB payloads before GeoDataFrame construction.
            
            df['geometry'] = geometries
            
            # Remove rows with null geometry
            df = df[df['geometry'].notna()]
        
        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
        
        # Rename columns for consistency
        column_mapping = {
            'num_floors': 'building_levels',
            'class': 'building_class'
        }
        gdf = gdf.rename(columns={k: v for k, v in column_mapping.items() if k in gdf.columns})

        # TODO: Normalize height fields so downstream pipeline can avoid per-consumer null/default coercion.
        
        return gdf
    
    def parse_geoparquet(
        self,
        s3_path: str,
        bbox: Optional[Tuple[float, float, float, float]] = None
    ) -> Optional[gpd.GeoDataFrame]:
        """
        Parse a GeoParquet file from S3 with optional bbox filtering.
        
        This method provides efficient streaming read of GeoParquet files
        using row group filtering for large datasets.
        
        Args:
            s3_path: Full S3 path to GeoParquet file
            bbox: Optional bounding box for filtering
            
        Returns:
            GeoDataFrame with parsed data
        """
        logger.info(f"Parsing GeoParquet from {s3_path}")
        
        try:
            # Open file from S3
            with self.s3_fs.open_input_file(s3_path) as f:
                # Read parquet metadata
                parquet_file = pq.ParquetFile(f)
                
                # Get row groups that intersect with bbox
                if bbox is not None:
                    row_groups = self._filter_row_groups(parquet_file, bbox)
                else:
                    row_groups = range(parquet_file.num_row_groups)
                
                # Read filtered row groups
                tables = []
                for rg_idx in row_groups:
                    table = parquet_file.read_row_group(rg_idx)
                    tables.append(table)
                
                if not tables:
                    return gpd.GeoDataFrame(columns=['geometry'], crs='EPSG:4326')
                
                # Concatenate tables
                combined_table = pa.concat_tables(tables)
                
                # Convert to GeoDataFrame
                return self._table_to_geodataframe(combined_table)
                
        except Exception as e:
            logger.error(f"Failed to parse GeoParquet: {e}")
            # TODO: Distinguish permission, malformed-schema, and transient read errors for caller-level fallback logic.
            return None
    
    def _filter_row_groups(
        self,
        parquet_file: pq.ParquetFile,
        bbox: Tuple[float, float, float, float]
    ) -> List[int]:
        """
        Filter row groups based on bbox intersection.
        
        Uses Parquet statistics to skip row groups that don't intersect.
        
        Args:
            parquet_file: Parquet file object
            bbox: Bounding box tuple
            
        Returns:
            List of row group indices to read
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        row_groups_to_read = []
        
        for rg_idx in range(parquet_file.num_row_groups):
            rg_meta = parquet_file.metadata.row_group(rg_idx)
            
            # Check if row group has bbox columns
            has_bbox = False
            rg_min_x = rg_max_x = rg_min_y = rg_max_y = None
            
            for col_idx in range(rg_meta.num_columns):
                col_meta = rg_meta.column(col_idx)
                col_name = col_meta.path_in_schema
                
                if 'bbox.minX' in str(col_name):
                    rg_min_x = col_meta.statistics.min
                    has_bbox = True
                elif 'bbox.maxX' in str(col_name):
                    rg_max_x = col_meta.statistics.max
                elif 'bbox.minY' in str(col_name):
                    rg_min_y = col_meta.statistics.min
                elif 'bbox.maxY' in str(col_name):
                    rg_max_y = col_meta.statistics.max
            
            # Check intersection if bbox stats available.
            if (
                has_bbox and
                rg_min_x is not None and
                rg_max_x is not None and
                rg_min_y is not None and
                rg_max_y is not None
            ):
                if (
                    rg_max_x < min_lon or rg_min_x > max_lon or
                    rg_max_y < min_lat or rg_min_y > max_lat
                ):
                    # Row group doesn't intersect - skip.
                    continue

            # Missing statistics: include row group and let row-level filter handle it.
            row_groups_to_read.append(rg_idx)
        
        logger.debug(
            f"Filtered to {len(row_groups_to_read)}/{parquet_file.num_row_groups} "
            f"row groups"
        )
        return row_groups_to_read
    
    def get_available_types(self) -> List[str]:
        """
        Get list of available building types in the dataset.
        
        Returns:
            List of building type strings
        """
        try:
            dataset = self._get_dataset()
            
            # Get unique values from 'class' column
            scanner = dataset.scanner(columns=["class"])
            table = scanner.to_table()
            
            unique_types = table.column("class").unique().to_pylist()
            return [t for t in unique_types if t is not None]
            
        except Exception as e:
            logger.error(f"Failed to get types: {e}")
            return []
    
    def get_dataset_info(self) -> Dict[str, Any]:
        """
        Get information about the Overture dataset.
        
        Returns:
            Dictionary with dataset metadata
        """
        try:
            dataset = self._get_dataset()
            
            return {
                'bucket': self.s3_bucket,
                'prefix': self.s3_prefix,
                'version': self.DATASET_VERSION,
                'attribution': self.ATTRIBUTION,
                'total_rows': dataset.count_rows(),
                'schema': str(dataset.schema) if dataset.schema else None,
                'partitioning': str(dataset.partitioning) if dataset.partitioning else None
            }
            
        except Exception as e:
            logger.error(f"Failed to get dataset info: {e}")
            return {
                'bucket': self.s3_bucket,
                'prefix': self.s3_prefix,
                'version': self.DATASET_VERSION,
                'attribution': self.ATTRIBUTION,
                'error': str(e)
            }
    
    def get_attribution(self) -> str:
        """
        Get the required ODbL attribution string.
        
        Returns:
            Attribution string for display
        """
        return (
            f"Building data: {self.ATTRIBUTION} | "
            f"Version: {self.DATASET_VERSION} | "
            f"https://overturemaps.org"
        )


class OvertureCache:
    """
    Local cache for Overture Maps data to reduce S3 requests.
    
    This class provides disk-based caching of queried building data
    for improved performance on repeated queries.
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the cache.
        
        Args:
            cache_dir: Directory for cache files (default: ~/.cache/linkspot/overture)
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "linkspot" / "overture"
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Overture cache initialized at {self.cache_dir}")
    
    def _get_cache_key(self, bbox: Tuple[float, float, float, float]) -> str:
        """Generate cache key from bbox."""
        bbox_str = f"{bbox[0]:.6f}_{bbox[1]:.6f}_{bbox[2]:.6f}_{bbox[3]:.6f}"
        return hashlib.md5(bbox_str.encode()).hexdigest()
    
    def _get_cache_path(self, bbox: Tuple[float, float, float, float]) -> Path:
        """Get cache file path for bbox."""
        cache_key = self._get_cache_key(bbox)
        return self.cache_dir / f"{cache_key}.parquet"
    
    def get(self, bbox: Tuple[float, float, float, float]) -> Optional[gpd.GeoDataFrame]:
        """
        Get cached data for bbox.
        
        Args:
            bbox: Bounding box tuple
            
        Returns:
            GeoDataFrame if cache hit, None otherwise
        """
        cache_path = self._get_cache_path(bbox)
        
        if cache_path.exists():
            try:
                gdf = gpd.read_parquet(cache_path)
                logger.debug(f"Cache hit for bbox {bbox}")
                return gdf
            except Exception as e:
                logger.warning(f"Failed to read cache: {e}")
        
        return None
    
    def set(
        self,
        bbox: Tuple[float, float, float, float],
        gdf: gpd.GeoDataFrame
    ) -> bool:
        """
        Cache data for bbox.
        
        Args:
            bbox: Bounding box tuple
            gdf: GeoDataFrame to cache
            
        Returns:
            True if caching succeeded
        """
        cache_path = self._get_cache_path(bbox)
        
        try:
            gdf.to_parquet(cache_path, index=False)
            logger.debug(f"Cached {len(gdf)} buildings for bbox {bbox}")
            return True
        except Exception as e:
            logger.warning(f"Failed to write cache: {e}")
            return False
    
    def clear(self) -> int:
        """
        Clear all cached data.
        
        Returns:
            Number of files removed
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.parquet"):
            try:
                cache_file.unlink()
                count += 1
            except Exception as e:
                logger.warning(f"Failed to remove {cache_file}: {e}")
        
        logger.info(f"Cleared {count} cached files")
        return count


# Convenience functions
def query_overture_buildings(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """
    Quick query function for Overture buildings.
    
    Args:
        min_lon: Minimum longitude
        min_lat: Minimum latitude
        max_lon: Maximum longitude
        max_lat: Maximum latitude
        
    Returns:
        GeoDataFrame with building data
    """
    client = OvertureMapsClient()
    return client.query_buildings((min_lon, min_lat, max_lon, max_lat))


if __name__ == '__main__':
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    client = OvertureMapsClient()
    
    # Get dataset info
    info = client.get_dataset_info()
    print(f"Dataset info: {info}")
    
    # Query buildings in Manhattan
    bbox = (-74.02, 40.70, -73.97, 40.78)  # Manhattan
    buildings = client.query_buildings(bbox)
    
    if buildings is not None:
        print(f"Found {len(buildings)} buildings")
        print(buildings.head())
        print(f"\nAttribution: {client.get_attribution()}")
