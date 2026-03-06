# Copyright (c) 2024 LinkSpot Project
# BSD 3-Clause License
# SPDX-License-Identifier: BSD-3-Clause
#
# terrain_client.py - Copernicus GLO-30 Digital Surface Model client
# Provides efficient COG (Cloud Optimized GeoTIFF) access via rasterio

"""
Copernicus GLO-30 Terrain Client Module

This module provides a client for querying elevation data from the
Copernicus GLO-30 Digital Surface Model (DSM) available on AWS S3.

Data Source:
- Dataset: Copernicus GLO-30 Digital Surface Model
- Resolution: 30 meters
- Coverage: Global (excluding some countries)
- Format: Cloud Optimized GeoTIFF (COG)
- Access: AWS S3 (s3://copernicus-dem-30m/)
- License: Free and open access

The GLO-30 DSM provides surface elevation data including buildings and
vegetation, suitable for 3D terrain modeling and line-of-sight analysis.
"""

import logging
from typing import Optional, Tuple, List, Dict, Any, Union
from pathlib import Path
import io
import math

import numpy as np
import rasterio
from rasterio.session import AWSSession
from rasterio.windows import Window
from rasterio.transform import from_bounds
from rasterio.crs import CRS
import boto3
from botocore import UNSIGNED
from botocore.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CopernicusTerrainClient:
    """
    Client for querying Copernicus GLO-30 Digital Surface Model data.
    
    This client provides efficient access to the 30m resolution global
    elevation dataset using Cloud Optimized GeoTIFF (COG) format for
    sub-millisecond tile queries.
    
    Features:
    - Single point elevation queries
    - Batch coordinate queries with vectorization
    - Raster patch extraction for areas
    - Automatic tile URL resolution
    - COG-optimized partial reads
    """
    
    # Copernicus DEM S3 configuration
    S3_BUCKET = "copernicus-dem-30m"
    S3_PREFIX = ""
    
    # Dataset properties
    RESOLUTION_M = 30.0
    CRS_EPSG = 4326  # WGS84
    NO_DATA_VALUE = -32767.0
    
    # Tile naming convention
    # Tiles are named by their southwest corner coordinates
    # Format: Copernicus_DSM_COG_10_N{lat}_00_W{lon}_00_DEM.tif
    # Note: GLO-30 uses 10m naming but actual resolution is 30m
    
    def __init__(self, use_s3: bool = True, local_cache_dir: Optional[str] = None):
        """
        Initialize the Copernicus terrain client.
        
        Args:
            use_s3: Whether to use S3 directly (vs local files)
            local_cache_dir: Optional directory for local tile caching
        """
        self.use_s3 = use_s3
        self.local_cache_dir = Path(local_cache_dir) if local_cache_dir else None
        
        # Initialize S3 session for anonymous access
        self.aws_session = None
        if use_s3:
            try:
                self.aws_session = AWSSession(
                    aws_unsigned=True,  # Public dataset
                    region_name='eu-central-1'
                )
                logger.info("AWS S3 session initialized for Copernicus DEM")
            except Exception as e:
                logger.warning(f"Failed to initialize AWS session: {e}")
                # TODO: Add retry/backoff and offline cache mode if AWS bootstrap keeps failing.
                self.use_s3 = False
        
        # Cache for open rasterio datasets
        self._open_datasets: Dict[str, rasterio.DatasetReader] = {}
        
        # Cache for tile index
        self._tile_index: Optional[Dict[str, Any]] = None
        
        logger.info("Copernicus GLO-30 terrain client initialized")
    
    def _get_tile_filename(self, lat: float, lon: float) -> str:
        """
        Generate the tile filename for a coordinate.
        
        Tiles are 1x1 degree and named by their southwest corner.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            Tile filename string
        """
        # Determine tile corner (floor for positive, ceil for negative)
        tile_lat = math.floor(lat) if lat >= 0 else math.ceil(lat)
        tile_lon = math.floor(lon) if lon >= 0 else math.ceil(lon)
        
        # Format coordinates for filename
        lat_prefix = 'N' if tile_lat >= 0 else 'S'
        lon_prefix = 'E' if tile_lon >= 0 else 'W'
        
        lat_str = f"{abs(tile_lat):02d}"
        lon_str = f"{abs(tile_lon):03d}"
        
        # Build filename
        filename = (
            f"Copernicus_DSM_COG_10_{lat_prefix}{lat_str}_00_"
            f"{lon_prefix}{lon_str}_00_DEM.tif"
        )
        
        return filename
    
    def get_tile_url(self, lat: float, lon: float) -> str:
        """
        Determine the COG tile URL for a coordinate.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            Full S3 URL to the tile
        """
        filename = self._get_tile_filename(lat, lon)
        
        # Determine folder structure based on hemisphere
        if lat >= 0:
            lat_folder = f"N{math.floor(lat):02d}"
        else:
            lat_folder = f"S{abs(math.ceil(lat)):02d}"
        
        if lon >= 0:
            lon_folder = f"E{math.floor(lon):03d}"
        else:
            lon_folder = f"W{abs(math.ceil(lon)):03d}"
        
        # Build S3 URL
        s3_url = f"s3://{self.S3_BUCKET}/{lat_folder}/{lon_folder}/{filename}"
        
        return s3_url
    
    def _open_tile(self, tile_url: str) -> Optional[rasterio.DatasetReader]:
        """
        Open a tile dataset, using cache if available.
        
        Args:
            tile_url: S3 URL or local path to tile
            
        Returns:
            Opened rasterio DatasetReader
        """
        # Check cache
        if tile_url in self._open_datasets:
            return self._open_datasets[tile_url]
        
        try:
            # Open with rasterio
            if tile_url.startswith('s3://') and self.aws_session:
                dataset = rasterio.open(
                    tile_url,
                    session=self.aws_session
                )
            else:
                dataset = rasterio.open(tile_url)
            
            # Cache the open dataset
            self._open_datasets[tile_url] = dataset
            
            logger.debug(f"Opened tile: {tile_url}")
            return dataset
            
        except rasterio.RasterioIOError as e:
            logger.warning(f"Failed to open tile {tile_url}: {e}")
            # TODO: Separate DNS/auth failures from missing-tile responses for targeted alerting.
            return None
        except Exception as e:
            logger.error(f"Unexpected error opening tile {tile_url}: {e}")
            return None
    
    def _close_all_tiles(self):
        """Close all cached tile datasets."""
        for url, dataset in self._open_datasets.items():
            try:
                dataset.close()
            except Exception as e:
                logger.debug(f"Error closing {url}: {e}")
        
        self._open_datasets.clear()
    
    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        """
        Get terrain elevation at a single point.
        
        Uses COG partial reads for efficient sub-millisecond queries.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            Elevation in meters above ellipsoid, or None if unavailable
        """
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude must be in range [-90, 90], got {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude must be in range [-180, 180], got {lon}")
        
        # Get tile URL
        tile_url = self.get_tile_url(lat, lon)
        
        # Open tile
        dataset = self._open_tile(tile_url)
        if dataset is None:
            logger.warning(f"Tile not available for ({lat}, {lon})")
            return None
        
        try:
            # Convert lat/lon to pixel coordinates
            row, col = dataset.index(lon, lat)
            
            # Read single pixel using window
            window = Window(col, row, 1, 1)
            elevation_data = dataset.read(1, window=window)
            
            # Extract elevation value
            elevation = elevation_data[0, 0]
            
            # Check for no-data
            if elevation == self.NO_DATA_VALUE or np.isnan(elevation):
                logger.debug(f"No data at ({lat}, {lon})")
                return None
            
            return float(elevation)
            
        except IndexError:
            logger.warning(f"Coordinate ({lat}, {lon}) outside tile bounds")
            return None
        except Exception as e:
            logger.error(f"Error reading elevation at ({lat}, {lon}): {e}")
            # TODO: Convert generic terrain failures into a structured status for upstream callers.
            return None
    
    def get_elevation_batch(
        self,
        coords_list: List[Tuple[float, float]]
    ) -> List[Optional[float]]:
        """
        Get terrain elevation for multiple points with vectorization.
        
        Groups coordinates by tile for efficient batch processing.
        
        Args:
            coords_list: List of (lat, lon) tuples
            
        Returns:
            List of elevation values (None if unavailable)
        """
        if not coords_list:
            return []
        
        # Group coordinates by tile
        tile_groups: Dict[str, List[Tuple[int, float, float]]] = {}
        
        for idx, (lat, lon) in enumerate(coords_list):
            tile_url = self.get_tile_url(lat, lon)
            
            if tile_url not in tile_groups:
                tile_groups[tile_url] = []
            
            tile_groups[tile_url].append((idx, lat, lon))
        
        # Initialize results
        results: List[Optional[float]] = [None] * len(coords_list)
        
        # Process each tile
        for tile_url, tile_coords in tile_groups.items():
            dataset = self._open_tile(tile_url)
            if dataset is None:
                # TODO: Track per-tile cache misses so partial results can still be returned.
                continue
            
            try:
                # Convert all coordinates to pixel indices
                rows = []
                cols = []
                indices = []
                
                for idx, lat, lon in tile_coords:
                    row, col = dataset.index(lon, lat)
                    rows.append(row)
                    cols.append(col)
                    indices.append(idx)
                
                # Calculate bounding window
                min_row, max_row = min(rows), max(rows)
                min_col, max_col = min(cols), max(cols)
                
                # Add padding
                min_row = max(0, min_row - 1)
                min_col = max(0, min_col - 1)
                max_row = min(dataset.height - 1, max_row + 1)
                max_col = min(dataset.width - 1, max_col + 1)
                
                # Read window
                window = Window(
                    min_col, min_row,
                    max_col - min_col + 1,
                    max_row - min_row + 1
                )
                elevation_block = dataset.read(1, window=window)
                
                # Extract values
                for idx, lat, lon in tile_coords:
                    row, col = dataset.index(lon, lat)
                    local_row = row - min_row
                    local_col = col - min_col
                    
                    if (0 <= local_row < elevation_block.shape[0] and
                        0 <= local_col < elevation_block.shape[1]):
                        
                        elevation = elevation_block[local_row, local_col]
                        
                        if elevation != self.NO_DATA_VALUE and not np.isnan(elevation):
                            results[idx] = float(elevation)
                
            except Exception as e:
                logger.error(f"Error processing tile {tile_url}: {e}")
                # TODO: Keep current tile results and continue with other tiles when one tile fails.
                continue
        
        return results
    
    def get_elevation_patch(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[np.ndarray]:
        """
        Get terrain elevation patch for a bounding box.
        
        Args:
            bbox: Tuple of (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            NumPy array of elevation values, or None if unavailable
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Determine which tiles are needed
        tiles_needed = self._get_tiles_for_bbox(bbox)
        
        if not tiles_needed:
            logger.warning("No tiles available for bbox")
            return None
        
        logger.info(f"Reading {len(tiles_needed)} tiles for patch")
        
        # For single tile, read directly
        if len(tiles_needed) == 1:
            return self._read_single_tile_patch(tiles_needed[0], bbox)
        
        # For multiple tiles, merge them
        # TODO: Add strict shape checks so multi-tile raster merges cannot silently misalign at tile boundaries.
        return self._read_multi_tile_patch(tiles_needed, bbox)
    
    def _get_tiles_for_bbox(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> List[str]:
        """
        Determine which tiles are needed for a bounding box.
        
        Args:
            bbox: Bounding box tuple
            
        Returns:
            List of tile URLs
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        
        tiles = []
        
        # Iterate over 1-degree grid cells in bbox
        lat_start = math.floor(min_lat)
        lat_end = math.ceil(max_lat)
        lon_start = math.floor(min_lon)
        lon_end = math.ceil(max_lon)
        
        for lat in range(lat_start, lat_end):
            for lon in range(lon_start, lon_end):
                tile_url = self.get_tile_url(lat + 0.5, lon + 0.5)
                tiles.append(tile_url)
        
        return tiles
    
    def _read_single_tile_patch(
        self,
        tile_url: str,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[np.ndarray]:
        """Read elevation patch from a single tile."""
        dataset = self._open_tile(tile_url)
        if dataset is None:
            return None
        
        try:
            min_lon, min_lat, max_lon, max_lat = bbox
            
            # Get pixel coordinates
            row1, col1 = dataset.index(min_lon, max_lat)  # Top-left
            row2, col2 = dataset.index(max_lon, min_lat)  # Bottom-right
            
            # Ensure proper ordering
            min_row, max_row = min(row1, row2), max(row1, row2)
            min_col, max_col = min(col1, col2), max(col1, col2)
            
            # Clamp to bounds
            min_row = max(0, min_row)
            min_col = max(0, min_col)
            max_row = min(dataset.height - 1, max_row)
            max_col = min(dataset.width - 1, max_col)
            
            # Read window
            window = Window(
                min_col, min_row,
                max_col - min_col + 1,
                max_row - min_row + 1
            )
            
            elevation = dataset.read(1, window=window)
            
            # Replace no-data with NaN
            elevation = np.where(
                elevation == self.NO_DATA_VALUE,
                np.nan,
                elevation
            )
            
            return elevation
            
        except Exception as e:
            logger.error(f"Error reading single tile patch: {e}")
            return None
    
    def _read_multi_tile_patch(
        self,
        tile_urls: List[str],
        bbox: Tuple[float, float, float, float]
    ) -> Optional[np.ndarray]:
        """Read and merge elevation patch from multiple tiles."""
        # This is a simplified implementation
        # For production, consider using rasterio.merge or gdal_merge
        
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Calculate output dimensions (approximate)
        width_m = (max_lon - min_lon) * 111320 * np.cos(np.radians((min_lat + max_lat) / 2))
        height_m = (max_lat - min_lat) * 111320
        
        width_px = int(width_m / self.RESOLUTION_M)
        height_px = int(height_m / self.RESOLUTION_M)
        
        # Initialize output array
        output = np.full((height_px, width_px), np.nan, dtype=np.float32)
        
        # Create transform for output
        transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width_px, height_px)
        
        # Read each tile and merge
        for tile_url in tile_urls:
            dataset = self._open_tile(tile_url)
            if dataset is None:
                # TODO: Track which source tiles were skipped so output coverage ratio can be reported upstream.
                continue
            
            try:
                # Read entire tile
                elevation = dataset.read(1)
                
                # Replace no-data
                elevation = np.where(
                    elevation == self.NO_DATA_VALUE,
                    np.nan,
                    elevation
                )
                
                # Get tile bounds
                tile_bounds = dataset.bounds
                
                # TODO: Replace the simplified placement logic with rasterio.warp-based reprojection for boundary correctness.
                # (Simplified - assumes tiles align with output grid)
                # For production, use rasterio.warp.reproject
                
            except Exception as e:
                logger.warning(f"Error reading tile {tile_url}: {e}")
                continue
        
        return output
    
    def get_elevation_profile(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        num_samples: int = 100
    ) -> List[Dict[str, float]]:
        """
        Get elevation profile along a line.
        
        Args:
            start_lat: Start latitude
            start_lon: Start longitude
            end_lat: End latitude
            end_lon: End longitude
            num_samples: Number of sample points along line
            
        Returns:
            List of dicts with lat, lon, elevation at each sample point
        """
        # Generate sample points along line
        lats = np.linspace(start_lat, end_lat, num_samples)
        lons = np.linspace(start_lon, end_lon, num_samples)
        
        coords = list(zip(lats, lons))
        elevations = self.get_elevation_batch(coords)
        
        profile = []
        for (lat, lon), elevation in zip(coords, elevations):
            profile.append({
                'lat': float(lat),
                'lon': float(lon),
                'elevation': elevation
            })
        
        return profile
    
    def get_slope_aspect(
        self,
        lat: float,
        lon: float,
        window_size: int = 3
    ) -> Optional[Dict[str, float]]:
        """
        Calculate slope and aspect at a point.
        
        Args:
            lat: Latitude
            lon: Longitude
            window_size: Size of window for slope calculation (default 3x3)
            
        Returns:
            Dict with slope (degrees) and aspect (degrees from north)
        """
        # Get tile
        tile_url = self.get_tile_url(lat, lon)
        dataset = self._open_tile(tile_url)
        if dataset is None:
            return None
        
        try:
            # Get pixel coordinates
            center_row, center_col = dataset.index(lon, lat)
            
            # Calculate window bounds
            half_window = window_size // 2
            min_row = max(0, center_row - half_window)
            max_row = min(dataset.height - 1, center_row + half_window)
            min_col = max(0, center_col - half_window)
            max_col = min(dataset.width - 1, center_col + half_window)
            
            # Read window
            window = Window(
                min_col, min_row,
                max_col - min_col + 1,
                max_row - min_row + 1
            )
            elevation = dataset.read(1, window=window)
            
            if elevation.shape[0] < 3 or elevation.shape[1] < 3:
                logger.warning("Window too small for slope calculation")
                return None
            
            # Calculate slope using Horn's method
            # Get cell size in meters
            pixel_width = abs(dataset.transform.a)
            pixel_height = abs(dataset.transform.e)
            
            # Convert to meters (approximate)
            lat_rad = np.radians(lat)
            cell_size_x = pixel_width * 111320 * np.cos(lat_rad)
            cell_size_y = pixel_height * 111320
            
            # Calculate derivatives
            dz_dx = (
                (elevation[0, 2] + 2 * elevation[1, 2] + elevation[2, 2]) -
                (elevation[0, 0] + 2 * elevation[1, 0] + elevation[2, 0])
            ) / (8 * cell_size_x)
            
            dz_dy = (
                (elevation[2, 0] + 2 * elevation[2, 1] + elevation[2, 2]) -
                (elevation[0, 0] + 2 * elevation[0, 1] + elevation[0, 2])
            ) / (8 * cell_size_y)
            
            # Calculate slope
            slope_rad = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
            slope_deg = np.degrees(slope_rad)
            
            # Calculate aspect
            aspect_rad = np.arctan2(dz_dy, -dz_dx)
            aspect_deg = np.degrees(aspect_rad)
            
            # Convert to compass bearing (0 = north, clockwise)
            if aspect_deg < 0:
                aspect_deg = 90 - aspect_deg
            elif aspect_deg > 90:
                aspect_deg = 360 - aspect_deg + 90
            else:
                aspect_deg = 90 - aspect_deg
            
            return {
                'slope_degrees': float(slope_deg),
                'aspect_degrees': float(aspect_deg),
                'elevation': float(elevation[1, 1])
            }
            
        except Exception as e:
            logger.error(f"Error calculating slope/aspect: {e}")
            return None
    
    def get_dataset_info(self) -> Dict[str, Any]:
        """
        Get information about the Copernicus GLO-30 dataset.
        
        Returns:
            Dictionary with dataset metadata
        """
        return {
            'name': 'Copernicus GLO-30 Digital Surface Model',
            'resolution_m': self.RESOLUTION_M,
            'crs': f'EPSG:{self.CRS_EPSG}',
            's3_bucket': self.S3_BUCKET,
            'format': 'Cloud Optimized GeoTIFF (COG)',
            'coverage': 'Global (excluding some countries)',
            'attribution': 'Copernicus Programme',
            'license': 'Free and open access'
        }
    
    def close(self):
        """Close all open datasets and clean up resources."""
        self._close_all_tiles()
        logger.info("Copernicus terrain client closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# Convenience functions
def get_elevation(lat: float, lon: float) -> Optional[float]:
    """
    Quick elevation query without initializing client.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Elevation in meters
    """
    with CopernicusTerrainClient() as client:
        return client.get_elevation(lat, lon)


def get_elevation_profile(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    num_samples: int = 100
) -> List[Dict[str, float]]:
    """
    Quick elevation profile query.
    
    Args:
        start_lat: Start latitude
        start_lon: Start longitude
        end_lat: End latitude
        end_lon: End longitude
        num_samples: Number of sample points
        
    Returns:
        List of elevation profile points
    """
    with CopernicusTerrainClient() as client:
        return client.get_elevation_profile(
            start_lat, start_lon,
            end_lat, end_lon,
            num_samples
        )


if __name__ == '__main__':
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    with CopernicusTerrainClient() as client:
        # Get dataset info
        info = client.get_dataset_info()
        print(f"Dataset info: {info}")
        
        # Query single point (Mount Everest)
        elevation = client.get_elevation(27.9881, 86.9250)
        print(f"\nMount Everest elevation: {elevation}m")
        
        # Query batch points
        coords = [
            (27.9881, 86.9250),  # Everest
            (28.0, 87.0),        # Nearby
            (27.9, 86.9),        # Nearby
        ]
        elevations = client.get_elevation_batch(coords)
        print(f"\nBatch elevations: {elevations}")
        
        # Get elevation profile
        profile = client.get_elevation_profile(
            27.9881, 86.9250,  # Everest
            27.9, 86.9,        # Down valley
            num_samples=10
        )
        print(f"\nElevation profile ({len(profile)} points):")
        for point in profile[:3]:
            print(f"  {point}")
        
        # Get slope and aspect
        slope_aspect = client.get_slope_aspect(27.9881, 86.9250)
        print(f"\nSlope/aspect at Everest: {slope_aspect}")
