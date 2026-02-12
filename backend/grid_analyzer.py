#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkSpot Grid Analyzer

BSD 3-Clause License

Copyright (c) 2024, LinkSpot Project Contributors
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

================================================================================

Grid Analysis for Heat Map Generation

This module provides grid-based analysis for generating coverage heat maps
over a geographic area. It creates a regular grid of analysis points and
computes the obstruction status for each point in parallel.

Performance Considerations:
--------------------------
- Grid analysis of ~320 points should complete in < 2 seconds
- Parallel processing using multiprocessing for CPU-bound calculations
- Vectorized NumPy operations where possible
- Efficient grid generation using ENU coordinate transformations

Grid Generation:
---------------
The grid is created in ENU coordinates to ensure regular spacing in meters,
then converted back to WGS84 for analysis. This avoids distortion from
latitude-dependent longitude scaling.

For a 500m x 500m grid with 28m spacing:
- Grid dimensions: 19 x 19 = 361 points (approximately 320 as specified)
- Spacing is configurable based on desired resolution
"""

import numpy as np
from typing import List, Tuple, Dict, Any, Optional, Iterator
from datetime import datetime
import json
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing as mp

# Import ENU utilities and obstruction engine
from enu_utils import wgs84_to_enu, enu_to_wgs84
from ray_casting_engine import ObstructionEngine, AnalysisResult, Zone

# Configure logging
logger = logging.getLogger(__name__)


class GridPoint:
    """
    Single point in the analysis grid.
    
    Attributes:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        elevation: Ground elevation in meters
        grid_i: Grid row index
        grid_j: Grid column index
        e: East coordinate relative to grid center (meters)
        n: North coordinate relative to grid center (meters)
    """
    
    def __init__(
        self,
        lat: float,
        lon: float,
        elevation: float,
        grid_i: int,
        grid_j: int,
        e: float = 0.0,
        n: float = 0.0
    ):
        self.lat = lat
        self.lon = lon
        self.elevation = elevation
        self.grid_i = grid_i
        self.grid_j = grid_j
        self.e = e
        self.n = n
    
    def to_tuple(self) -> Tuple[float, float, float]:
        """Return (lat, lon, elevation) tuple."""
        return (self.lat, self.lon, self.elevation)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'lat': self.lat,
            'lon': self.lon,
            'elevation': self.elevation,
            'grid_i': self.grid_i,
            'grid_j': self.grid_j,
            'e': self.e,
            'n': self.n
        }


class GridResult:
    """
    Result of grid analysis for a single point.
    
    Combines the grid point location with the analysis result.
    """
    
    def __init__(self, grid_point: GridPoint, analysis: AnalysisResult):
        self.grid_point = grid_point
        self.analysis = analysis
    
    @property
    def zone(self) -> Zone:
        """Get zone classification."""
        return self.analysis.zone
    
    @property
    def n_clear(self) -> int:
        """Get number of clear-LOS satellites."""
        return self.analysis.n_clear
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'point': self.grid_point.to_dict(),
            'analysis': self.analysis.to_dict()
        }


class GridAnalyzer:
    """
    Grid-based analysis for coverage heat map generation.
    
    This class creates a regular grid of analysis points over a geographic
    area and computes the obstruction status for each point. Results can
    be exported to GeoJSON for visualization in the frontend.
    
    Usage:
        analyzer = GridAnalyzer(obstruction_engine)
        grid = analyzer.create_analysis_grid(center_lat, center_lon, 500, 28)
        results = analyzer.analyze_grid(grid, timestamp)
        geojson = analyzer.grid_to_geojson(results)
    
    Attributes:
        obstruction_engine: ObstructionEngine instance for analysis
        n_workers: Number of parallel workers for grid analysis
        use_multiprocessing: Whether to use multiprocessing vs threading
    """
    
    def __init__(
        self,
        obstruction_engine: ObstructionEngine,
        n_workers: Optional[int] = None,
        use_multiprocessing: bool = True
    ):
        """
        Initialize the grid analyzer.
        
        Args:
            obstruction_engine: Configured ObstructionEngine instance
            n_workers: Number of parallel workers (default: CPU count)
            use_multiprocessing: Use processes (True) or threads (False)
        """
        self.obstruction_engine = obstruction_engine
        self.n_workers = n_workers or mp.cpu_count()
        self.use_multiprocessing = use_multiprocessing
        
        logger.info(
            f"GridAnalyzer initialized: "
            f"n_workers={self.n_workers}, "
            f"multiprocessing={use_multiprocessing}"
        )
    
    def create_analysis_grid(
        self,
        center_lat: float,
        center_lon: float,
        size_m: float = 500.0,
        spacing_m: float = 28.0,
        center_elevation: float = 0.0
    ) -> List[GridPoint]:
        """
        Create a regular grid of analysis points.
        
        The grid is created in ENU coordinates to ensure regular spacing
        in meters, then converted to WGS84 for geographic positions.
        
        Grid layout:
        - Center point at (center_lat, center_lon)
        - Extends size_m/2 in each direction from center
        - Points spaced spacing_m meters apart
        
        For 500m size with 28m spacing:
        - Half-size = 250m
        - Points from -250 to +250 in both E and N directions
        - 19 points per dimension = 361 total points
        
        Args:
            center_lat: Grid center latitude (decimal degrees)
            center_lon: Grid center longitude (decimal degrees)
            size_m: Grid size in meters (default 500 = 500m x 500m)
            spacing_m: Grid spacing in meters (default 28m)
            center_elevation: Ground elevation at center point (meters)
        
        Returns:
            List of GridPoint objects in row-major order
        
        Example:
            >>> grid = analyzer.create_analysis_grid(40.7128, -74.0060, 500, 28)
            >>> print(f"Created grid with {len(grid)} points")
        """
        half_size = size_m / 2.0
        
        # Generate grid coordinates in ENU (meters from center)
        # Use arange to get exact spacing, ensuring we include edges
        n_points = int(np.ceil(size_m / spacing_m)) + 1
        coords = np.linspace(-half_size, half_size, n_points)
        
        grid_points = []
        
        # Create grid in row-major order (N varies slowest, E varies fastest)
        for i, n in enumerate(coords):
            for j, e in enumerate(coords):
                # Convert ENU offset to WGS84
                lat, lon, elev = enu_to_wgs84(
                    e, n, 0.0,  # U=0 because we're on the ground
                    center_lat, center_lon, center_elevation
                )
                
                grid_points.append(GridPoint(
                    lat=lat,
                    lon=lon,
                    elevation=elev,
                    grid_i=i,
                    grid_j=j,
                    e=e,
                    n=n
                ))
        
        logger.info(
            f"Created {len(grid_points)} grid points: "
            f"{n_points}x{n_points} grid, {size_m}m x {size_m}m, "
            f"{spacing_m}m spacing"
        )
        
        return grid_points
    
    def analyze_grid(
        self,
        grid_points: List[GridPoint],
        timestamp: Optional[datetime] = None,
        radius_m: float = 500.0,
        parallel: bool = True
    ) -> List[GridResult]:
        """
        Analyze all grid points for obstruction status.
        
        This method computes the obstruction profile and satellite visibility
        for each grid point. It supports parallel processing for improved
        performance on multi-core systems.
        
        Performance target: < 2 seconds for ~320 points
        
        Args:
            grid_points: List of GridPoint objects to analyze
            timestamp: Analysis timestamp (default: current UTC)
            radius_m: Search radius for buildings (default 500m)
            parallel: Whether to use parallel processing (default True)
        
        Returns:
            List of GridResult objects (same order as input)
        
        Example:
            >>> grid = analyzer.create_analysis_grid(40.7128, -74.0060)
            >>> results = analyzer.analyze_grid(grid)
            >>> green_count = sum(1 for r in results if r.zone == Zone.GREEN)
        """
        import time
        start_time = time.perf_counter()
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        if not parallel or len(grid_points) < 10:
            # Sequential processing for small grids
            results = self._analyze_sequential(grid_points, timestamp, radius_m)
        else:
            # Parallel processing for larger grids
            results = self._analyze_parallel(grid_points, timestamp, radius_m)
        
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Grid analysis complete: {len(grid_points)} points in {elapsed:.1f}ms "
            f"({elapsed/len(grid_points):.1f}ms per point)"
        )
        
        return results
    
    def _analyze_sequential(
        self,
        grid_points: List[GridPoint],
        timestamp: datetime,
        radius_m: float
    ) -> List[GridResult]:
        """Analyze grid points sequentially (single-threaded)."""
        results = []
        
        for point in grid_points:
            analysis = self.obstruction_engine.analyze_position(
                lat=point.lat,
                lon=point.lon,
                elevation=point.elevation,
                timestamp=timestamp,
                radius_m=radius_m
            )
            results.append(GridResult(point, analysis))
        
        return results
    
    def _analyze_parallel(
        self,
        grid_points: List[GridPoint],
        timestamp: datetime,
        radius_m: float
    ) -> List[GridResult]:
        """Analyze grid points in parallel using process/thread pool."""
        # Prepare arguments for each worker
        args_list = [
            (point, timestamp, radius_m)
            for point in grid_points
        ]
        
        # Choose executor type
        ExecutorClass = ProcessPoolExecutor if self.use_multiprocessing else ThreadPoolExecutor
        
        results = [None] * len(grid_points)
        
        with ExecutorClass(max_workers=self.n_workers) as executor:
            # Submit all tasks and collect futures
            futures = {
                executor.submit(
                    self._analyze_single_point,
                    self.obstruction_engine,
                    point,
                    timestamp,
                    radius_m
                ): idx
                for idx, (point, timestamp, radius_m) in enumerate(args_list)
            }
            
            # Collect results as they complete
            for future in futures:
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error(f"Error analyzing grid point {idx}: {e}")
                    # Create a default DEAD zone result on error
                    error_analysis = AnalysisResult(
                        zone=Zone.DEAD,
                        n_clear=0,
                        n_total=0,
                        obstruction_pct=100.0,
                        blocked_azimuths=[],
                        obstruction_profile=np.full(
                            self.obstruction_engine.n_sectors, 90.0
                        ),
                        timestamp=timestamp
                    )
                    results[idx] = GridResult(grid_points[idx], error_analysis)
        
        return results
    
    @staticmethod
    def _analyze_single_point(
        engine: ObstructionEngine,
        point: GridPoint,
        timestamp: datetime,
        radius_m: float
    ) -> GridResult:
        """Static method for analyzing a single point (for parallel execution)."""
        analysis = engine.analyze_position(
            lat=point.lat,
            lon=point.lon,
            elevation=point.elevation,
            timestamp=timestamp,
            radius_m=radius_m
        )
        return GridResult(point, analysis)
    
    def grid_to_geojson(
        self,
        results: List[GridResult],
        include_profile: bool = False
    ) -> Dict[str, Any]:
        """
        Convert grid analysis results to GeoJSON format.

GeoJSON is a standard format for geographic data that can be easily
        visualized in web mapping libraries like Leaflet or Mapbox.
        
        Each grid point becomes a GeoJSON Feature with:
        - Geometry: Point with [lon, lat, elevation] coordinates
        - Properties: Zone classification, satellite counts, etc.
        
        Args:
            results: List of GridResult objects from analyze_grid()
            include_profile: Whether to include full obstruction profile
        
        Returns:
            GeoJSON FeatureCollection dictionary
        
        Example:
            >>> results = analyzer.analyze_grid(grid)
            >>> geojson = analyzer.grid_to_geojson(results)
            >>> with open('coverage.geojson', 'w') as f:
            ...     json.dump(geojson, f)
        """
        features = []
        
        for result in results:
            point = result.grid_point
            analysis = result.analysis
            
            # Create GeoJSON Feature
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [point.lon, point.lat, point.elevation]
                },
                'properties': {
                    'zone': analysis.zone.value,
                    'n_clear': analysis.n_clear,
                    'n_total': analysis.n_total,
                    'obstruction_pct': round(analysis.obstruction_pct, 2),
                    'grid_i': point.grid_i,
                    'grid_j': point.grid_j,
                    'e': round(point.e, 2),
                    'n': round(point.n, 2),
                    'processing_time_ms': round(analysis.processing_time_ms, 2) if analysis.processing_time_ms else None
                }
            }
            
            # Optionally include full obstruction profile
            if include_profile:
                feature['properties']['obstruction_profile'] = [
                    round(float(e), 2) for e in analysis.obstruction_profile
                ]
            
            features.append(feature)
        
        # Create FeatureCollection
        geojson = {
            'type': 'FeatureCollection',
            'metadata': {
                'generated_at': datetime.utcnow().isoformat(),
                'total_points': len(results),
                'zone_counts': self._count_zones(results),
                'satellite_threshold': self.obstruction_engine.sat_threshold,
                'min_elevation': self.obstruction_engine.min_elevation
            },
            'features': features
        }
        
        return geojson
    
    def grid_to_heatmap_array(
        self,
        results: List[GridResult]
    ) -> np.ndarray:
        """
        Convert grid results to a 2D numpy array for heat map visualization.
        
        The array contains integer values representing zone classifications:
        - 2: GREEN zone (good coverage)
        - 1: AMBER zone (marginal coverage)
        - 0: DEAD zone (no coverage)
        
        Args:
            results: List of GridResult objects
        
        Returns:
            2D numpy array of zone values, shape (n_rows, n_cols)
        """
        if not results:
            return np.array([])
        
        # Determine grid dimensions
        max_i = max(r.grid_point.grid_i for r in results)
        max_j = max(r.grid_point.grid_j for r in results)
        
        # Create 2D array
        heatmap = np.zeros((max_i + 1, max_j + 1), dtype=np.int32)
        
        # Fill with zone values
        zone_values = {Zone.GREEN: 2, Zone.AMBER: 1, Zone.DEAD: 0}
        
        for result in results:
            i = result.grid_point.grid_i
            j = result.grid_point.grid_j
            heatmap[i, j] = zone_values[result.zone]
        
        return heatmap
    
    def grid_to_satellite_count_array(
        self,
        results: List[GridResult]
    ) -> np.ndarray:
        """
        Convert grid results to a 2D array of clear satellite counts.
        
        This provides a more detailed view than the zone classification,
        showing the actual number of clear-LOS satellites at each point.
        
        Args:
            results: List of GridResult objects
        
        Returns:
            2D numpy array of satellite counts, shape (n_rows, n_cols)
        """
        if not results:
            return np.array([])
        
        max_i = max(r.grid_point.grid_i for r in results)
        max_j = max(r.grid_point.grid_j for r in results)
        
        counts = np.zeros((max_i + 1, max_j + 1), dtype=np.int32)
        
        for result in results:
            i = result.grid_point.grid_i
            j = result.grid_point.grid_j
            counts[i, j] = result.n_clear
        
        return counts
    
    def export_to_json(
        self,
        results: List[GridResult],
        filepath: str,
        include_profile: bool = False
    ) -> None:
        """
        Export grid results to a JSON file.
        
        Args:
            results: List of GridResult objects
            filepath: Output file path
            include_profile: Whether to include obstruction profiles
        """
        geojson = self.grid_to_geojson(results, include_profile)
        
        with open(filepath, 'w') as f:
            json.dump(geojson, f, indent=2)
        
        logger.info(f"Exported grid results to {filepath}")
    
    def _count_zones(self, results: List[GridResult]) -> Dict[str, int]:
        """Count occurrences of each zone type."""
        counts = {'green': 0, 'amber': 0, 'dead': 0}
        for result in results:
            counts[result.zone.value] += 1
        return counts
    
    def get_coverage_statistics(self, results: List[GridResult]) -> Dict[str, Any]:
        """
        Compute coverage statistics for the analyzed grid.
        
        Args:
            results: List of GridResult objects
        
        Returns:
            Dictionary with coverage statistics
        """
        if not results:
            return {}
        
        total = len(results)
        zone_counts = self._count_zones(results)
        
        n_clear_values = [r.n_clear for r in results]
        obstruction_pcts = [r.analysis.obstruction_pct for r in results]
        
        stats = {
            'total_points': total,
            'zone_counts': zone_counts,
            'zone_percentages': {
                zone: (count / total) * 100
                for zone, count in zone_counts.items()
            },
            'satellite_stats': {
                'mean_clear': np.mean(n_clear_values),
                'min_clear': np.min(n_clear_values),
                'max_clear': np.max(n_clear_values),
                'std_clear': np.std(n_clear_values)
            },
            'obstruction_stats': {
                'mean_pct': np.mean(obstruction_pcts),
                'min_pct': np.min(obstruction_pcts),
                'max_pct': np.max(obstruction_pcts)
            }
        }
        
        return stats


def create_grid_analyzer(
    satellite_engine: Any,
    data_pipeline: Any,
    min_elevation: float = 25.0,
    sat_threshold: int = 4,
    n_workers: Optional[int] = None
) -> GridAnalyzer:
    """
    Factory function to create a fully configured GridAnalyzer.
    
    Args:
        satellite_engine: Satellite engine instance
        data_pipeline: Data pipeline instance
        min_elevation: Minimum satellite elevation (degrees)
        sat_threshold: Minimum satellites for GREEN zone
        n_workers: Number of parallel workers
    
    Returns:
        Configured GridAnalyzer instance
    """
    from ray_casting_engine import ObstructionEngine
    
    obstruction_engine = ObstructionEngine(
        satellite_engine=satellite_engine,
        data_pipeline=data_pipeline,
        min_elevation=min_elevation,
        sat_threshold=sat_threshold
    )
    
    return GridAnalyzer(
        obstruction_engine=obstruction_engine,
        n_workers=n_workers
    )


# Example usage and testing
if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    # Create mock engines for testing
    from ray_casting_engine import MockSatelliteEngine, MockDataPipeline
    
    sat_engine = MockSatelliteEngine(n_satellites=12)
    data_pipeline = MockDataPipeline(n_buildings=30)
    
    # Create grid analyzer
    analyzer = create_grid_analyzer(
        satellite_engine=sat_engine,
        data_pipeline=data_pipeline,
        min_elevation=25.0,
        sat_threshold=4
    )
    
    # Create analysis grid
    center_lat, center_lon = 40.7128, -74.0060  # NYC
    grid = analyzer.create_analysis_grid(
        center_lat=center_lat,
        center_lon=center_lon,
        size_m=500,
        spacing_m=28
    )
    
    print(f"Created grid with {len(grid)} points")
    
    # Analyze grid
    results = analyzer.analyze_grid(grid, parallel=True)
    
    # Get statistics
    stats = analyzer.get_coverage_statistics(results)
    print(f"\nCoverage Statistics:")
    print(f"  Total points: {stats['total_points']}")
    print(f"  Zone distribution: {stats['zone_percentages']}")
    print(f"  Mean clear satellites: {stats['satellite_stats']['mean_clear']:.1f}")
    
    # Export to GeoJSON
    geojson = analyzer.grid_to_geojson(results)
    print(f"\nGeoJSON features: {len(geojson['features'])}")
