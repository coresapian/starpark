#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LinkSpot Ray-Casting Obstruction Engine

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

Ray-Casting Obstruction Algorithm for Satellite Line-of-Sight Analysis

This module implements the core intersection engine that determines whether
a parking position has clear RF line-of-sight to sufficient satellites.

Algorithm Overview:
-------------------
1. INPUT: User position (lat, lon, ground_elevation), timestamp, search radius
2. SATELLITE PASS: Query visible satellites (azimuth, elevation above threshold)
3. OBSTRUCTION PROFILE: For each azimuth sector (2° increments):
   a. Query buildings within search radius along that azimuth bearing
   b. Compute elevation angle to each building top
   c. Store maximum elevation angle = obstruction_elevation[sector]
4. INTERSECTION: For each satellite:
   a. Look up obstruction_elevation at satellite's azimuth sector
   b. If sat_elevation > obstruction_elevation: LOS is CLEAR
   c. If sat_elevation ≤ obstruction_elevation: LOS is BLOCKED
5. CLASSIFICATION: Count clear-LOS satellites and classify zone

Key Geometric Principle:
------------------------
The obstruction profile creates a "silhouette" of the surrounding buildings
as seen from the user's position. Each azimuth sector stores the minimum
elevation angle that a satellite must exceed to have clear line-of-sight.

This is equivalent to computing the upper envelope of all building elevation
angles as a function of azimuth.

Performance Optimizations:
--------------------------
- Vectorized NumPy operations for all geometric calculations
- Pre-computed azimuth sector lookups
- Efficient building filtering using ENU coordinate bounds
- Batch processing for multiple positions
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union
from enum import Enum
from datetime import datetime
import logging

# Import ENU utilities
from enu_utils import (
    wgs84_to_enu,
    calculate_azimuth,
    calculate_elevation_angle,
    azimuth_to_sector_index,
    sector_index_to_azimuth,
    calculate_horizontal_distance,
    is_within_radius
)

# Configure logging
logger = logging.getLogger(__name__)


class Zone(Enum):
    """
    Zone classification based on clear-LOS satellite count.
    
    GREEN: Adequate satellites for reliable positioning
    AMBER: Marginal coverage - positioning may be degraded
    DEAD: Insufficient satellites - no reliable positioning
    """
    GREEN = "green"
    AMBER = "amber"
    DEAD = "dead"


@dataclass
class AnalysisResult:
    """
    Complete result of a single position analysis.
    
    Attributes:
        zone: Zone classification (GREEN/AMBER/DEAD)
        n_clear: Number of satellites with clear line-of-sight
        n_total: Total number of visible satellites above min elevation
        obstruction_pct: Percentage of azimuth sectors blocked (0-100)
        blocked_azimuths: List of azimuth angles (degrees) where LOS is blocked
        obstruction_profile: 180-element array of max obstruction elevation per sector
        timestamp: Analysis timestamp
        lat: Latitude of analyzed position
        lon: Longitude of analyzed position
        elevation: Ground elevation at analyzed position (meters)
        processing_time_ms: Time taken for analysis (milliseconds)
    """
    zone: Zone
    n_clear: int
    n_total: int
    obstruction_pct: float
    blocked_azimuths: List[float]
    obstruction_profile: np.ndarray = field(repr=False)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation: Optional[float] = None
    processing_time_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        return {
            "zone": self.zone.value,
            "n_clear": self.n_clear,
            "n_total": self.n_total,
            "obstruction_pct": round(self.obstruction_pct, 2),
            "blocked_azimuths": [round(a, 1) for a in self.blocked_azimuths],
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "lat": self.lat,
            "lon": self.lon,
            "elevation": self.elevation,
            "processing_time_ms": round(self.processing_time_ms, 3) if self.processing_time_ms else None
        }


@dataclass
class Satellite:
    """
    Satellite position and visibility data.
    
    Attributes:
        prn: Pseudo-random noise code (unique satellite identifier)
        azimuth: Azimuth angle from user position (degrees, 0-360)
        elevation: Elevation angle above horizon (degrees, -90 to 90)
        system: GNSS constellation (GPS, GLONASS, Galileo, BeiDou)
    """
    prn: str
    azimuth: float
    elevation: float
    system: str = "GPS"


@dataclass
class Building:
    """
    Building data for obstruction calculation.
    
    Attributes:
        e: East coordinate relative to analysis center (meters)
        n: North coordinate relative to analysis center (meters)
        height: Building roof height above ground (meters)
        base_elevation: Ground elevation at building location (meters)
        footprint_area: Building footprint area (square meters, optional)
    """
    e: float
    n: float
    height: float
    base_elevation: float = 0.0
    footprint_area: Optional[float] = None
    
    @property
    def roof_height(self) -> float:
        """Total roof height above reference elevation."""
        return self.base_elevation + self.height


class ObstructionEngine:
    """
    Main engine for ray-casting obstruction analysis.
    
    This class implements the core algorithm for determining whether
    a position has clear RF line-of-sight to satellites, considering
    building obstructions in the surrounding environment.
    
    Usage:
        engine = ObstructionEngine(satellite_engine, data_pipeline)
        result = engine.analyze_position(lat, lon, elevation, timestamp)
    
    Attributes:
        satellite_engine: Interface to query visible satellites
        data_pipeline: Interface to query building data
        min_elevation: Minimum satellite elevation angle (degrees)
        sat_threshold: Minimum clear-LOS satellites for GREEN zone
        sector_width: Azimuth sector width for obstruction profile (degrees)
        n_sectors: Number of azimuth sectors (360 / sector_width)
    """
    
    def __init__(
        self,
        satellite_engine: Any,
        data_pipeline: Any,
        min_elevation: float = 25.0,
        sat_threshold: int = 4,
        sector_width: float = 2.0
    ):
        """
        Initialize the obstruction engine.
        
        Args:
            satellite_engine: Object with get_visible_satellites(lat, lon, elevation, timestamp, min_elevation) method
            data_pipeline: Object with get_buildings_in_radius(lat, lon, radius_m) method
            min_elevation: Minimum satellite elevation for visibility (default 25°)
            sat_threshold: Minimum satellites for GREEN zone (default 4)
            sector_width: Azimuth sector width (default 2° = 180 sectors)
        """
        self.satellite_engine = satellite_engine
        self.data_pipeline = data_pipeline
        self.min_elevation = min_elevation
        self.sat_threshold = sat_threshold
        self.sector_width = sector_width
        self.n_sectors = int(360.0 / sector_width)
        
        logger.info(
            f"ObstructionEngine initialized: "
            f"min_elevation={min_elevation}°, "
            f"sat_threshold={sat_threshold}, "
            f"sector_width={sector_width}° ({self.n_sectors} sectors)"
        )
    
    def analyze_position(
        self,
        lat: float,
        lon: float,
        elevation: float,
        timestamp: Optional[datetime] = None,
        radius_m: float = 500.0
    ) -> AnalysisResult:
        """
        Analyze a single position for satellite line-of-sight obstructions.
        
        This is the main entry point for position analysis. It:
        1. Queries visible satellites above min_elevation
        2. Computes the obstruction profile for surrounding buildings
        3. Determines which satellites have clear LOS
        4. Classifies the zone based on clear-LOS count
        
        Args:
            lat: Latitude in decimal degrees (-90 to 90)
            lon: Longitude in decimal degrees (-180 to 180)
            elevation: Ground elevation above WGS84 ellipsoid (meters)
            timestamp: Analysis time (default: current UTC time)
            radius_m: Search radius for buildings (default 500m)
        
        Returns:
            AnalysisResult with zone classification and detailed data
        
        Performance target: < 50ms for single position
        """
        import time
        start_time = time.perf_counter()
        
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Step 1: Query visible satellites
        satellites = self._get_visible_satellites(lat, lon, elevation, timestamp)
        n_total = len(satellites)
        
        if n_total == 0:
            # No satellites visible - definitely a dead zone
            processing_time = (time.perf_counter() - start_time) * 1000
            return AnalysisResult(
                zone=Zone.DEAD,
                n_clear=0,
                n_total=0,
                obstruction_pct=100.0,
                blocked_azimuths=list(np.arange(0, 360, self.sector_width)),
                obstruction_profile=np.full(self.n_sectors, 90.0),
                timestamp=timestamp,
                lat=lat,
                lon=lon,
                elevation=elevation,
                processing_time_ms=processing_time
            )
        
        # Step 2: Compute obstruction profile
        obstruction_profile = self.compute_obstruction_profile(
            lat, lon, elevation, radius_m
        )
        
        # Step 3: Check each satellite for clear LOS
        clear_satellites = []
        blocked_satellites = []
        
        for sat in satellites:
            # Get obstruction elevation at satellite's azimuth sector
            sector_idx = azimuth_to_sector_index(sat.azimuth, self.sector_width)
            obstruction_elev = obstruction_profile[sector_idx]
            
            # Compare satellite elevation to obstruction
            if sat.elevation > obstruction_elev:
                clear_satellites.append(sat)
            else:
                blocked_satellites.append(sat)
        
        n_clear = len(clear_satellites)
        
        # Step 4: Calculate blocked azimuth sectors
        blocked_azimuths = self._get_blocked_azimuths(
            obstruction_profile, satellites
        )
        
        # Step 5: Calculate obstruction percentage
        obstruction_pct = self.calculate_obstruction_percentage(
            len(blocked_azimuths)
        )
        
        # Step 6: Classify zone
        zone = self.classify_zone(n_clear)
        
        processing_time = (time.perf_counter() - start_time) * 1000
        
        logger.debug(
            f"Position ({lat:.6f}, {lon:.6f}): "
            f"zone={zone.value}, n_clear={n_clear}/{n_total}, "
            f"time={processing_time:.2f}ms"
        )
        
        return AnalysisResult(
            zone=zone,
            n_clear=n_clear,
            n_total=n_total,
            obstruction_pct=obstruction_pct,
            blocked_azimuths=blocked_azimuths,
            obstruction_profile=obstruction_profile,
            timestamp=timestamp,
            lat=lat,
            lon=lon,
            elevation=elevation,
            processing_time_ms=processing_time
        )
    
    def compute_obstruction_profile(
        self,
        lat: float,
        lon: float,
        elevation: float,
        radius_m: float = 500.0
    ) -> np.ndarray:
        """
        Compute the obstruction elevation profile for all azimuth sectors.
        
        The obstruction profile is a 180-element array where each element
        contains the maximum elevation angle of buildings in that azimuth
        sector. This creates a "silhouette" of the surrounding environment.
        
        Algorithm:
        1. Query all buildings within search radius
        2. Convert building positions to ENU coordinates relative to user
        3. For each building, compute:
           - Azimuth from user to building
           - Horizontal distance in E-N plane
           - Elevation angle to building top
        4. For each azimuth sector, store the maximum elevation angle
        
        Args:
            lat: User latitude (decimal degrees)
            lon: User longitude (decimal degrees)
            elevation: User ground elevation (meters)
            radius_m: Search radius for buildings (meters)
        
        Returns:
            numpy.ndarray: Shape (n_sectors,) array of max obstruction elevation
                          per sector in degrees. -90 means no obstruction.
        """
        # Initialize obstruction profile to minimum (no obstruction)
        # Using -90° as "no obstruction" since no real obstruction can be below horizon
        obstruction_profile = np.full(self.n_sectors, -90.0)
        
        # Query buildings within search radius
        buildings = self._get_buildings_in_radius(lat, lon, radius_m)
        
        if len(buildings) == 0:
            # No buildings - completely clear view
            return obstruction_profile
        
        # Convert buildings to ENU coordinates relative to user position
        building_data = self._convert_buildings_to_enu(
            buildings, lat, lon, elevation
        )
        
        if len(building_data) == 0:
            return obstruction_profile
        
        # Vectorized computation of azimuth and elevation for all buildings
        # Extract arrays for vectorized operations
        e_coords = building_data['e']
        n_coords = building_data['n']
        roof_heights = building_data['roof_height']
        
        # Compute azimuth from user (0,0) to each building
        # atan2(E, N) gives angle from North toward East
        azimuths = np.degrees(np.arctan2(e_coords, n_coords))
        azimuths = np.mod(azimuths, 360.0)  # Normalize to [0, 360)
        
        # Compute horizontal distance in E-N plane
        horizontal_dists = np.sqrt(e_coords * e_coords + n_coords * n_coords)
        
        # Filter out buildings at zero distance (shouldn't happen, but safety check)
        valid_mask = horizontal_dists > 0.1
        if not np.any(valid_mask):
            return obstruction_profile
        
        azimuths = azimuths[valid_mask]
        horizontal_dists = horizontal_dists[valid_mask]
        roof_heights = roof_heights[valid_mask]
        
        # Compute elevation angle to each building top
        # Elevation = atan2(height_diff, horizontal_distance)
        height_diffs = roof_heights - elevation
        elevation_angles = np.degrees(np.arctan2(height_diffs, horizontal_dists))
        
        # Convert azimuths to sector indices
        sector_indices = azimuth_to_sector_index(azimuths, self.sector_width)
        
        # For each sector, find the maximum elevation angle
        # Use numpy's advanced indexing with reduceat for efficiency
        # Sort by sector index to group by sector
        sort_idx = np.argsort(sector_indices)
        sorted_sectors = sector_indices[sort_idx]
        sorted_elevations = elevation_angles[sort_idx]
        
        # Find unique sectors and their maximum elevations
        unique_sectors = np.unique(sorted_sectors)
        
        for sector in unique_sectors:
            mask = sorted_sectors == sector
            max_elevation = np.max(sorted_elevations[mask])
            obstruction_profile[sector] = max_elevation
        
        return obstruction_profile
    
    def classify_zone(self, n_clear: int) -> Zone:
        """
        Classify the coverage zone based on clear-LOS satellite count.
        
        Classification rules:
        - GREEN: n_clear >= sat_threshold (default 4)
        - AMBER: 2 <= n_clear < sat_threshold (default 2-3)
        - DEAD: n_clear < 2
        
        Args:
            n_clear: Number of satellites with clear line-of-sight
        
        Returns:
            Zone classification (GREEN, AMBER, or DEAD)
        """
        if n_clear >= self.sat_threshold:
            return Zone.GREEN
        elif n_clear >= 2:
            return Zone.AMBER
        else:
            return Zone.DEAD
    
    def calculate_obstruction_percentage(
        self,
        blocked_sectors: int
    ) -> float:
        """
        Calculate the percentage of azimuth sectors that are obstructed.
        
        This metric indicates how much of the sky dome is blocked by
        buildings, independent of satellite positions.
        
        Args:
            blocked_sectors: Number of azimuth sectors with obstruction
        
        Returns:
            Obstruction percentage (0-100)
        """
        return (blocked_sectors / self.n_sectors) * 100.0
    
    def _get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float,
        timestamp: datetime
    ) -> List[Satellite]:
        """
        Query the satellite engine for visible satellites.
        
        Args:
            lat: User latitude
            lon: User longitude
            elevation: User elevation
            timestamp: Analysis timestamp
        
        Returns:
            List of Satellite objects above min_elevation
        """
        try:
            # Call satellite engine to get visible satellites
            sat_data = self.satellite_engine.get_visible_satellites(
                lat=lat,
                lon=lon,
                elevation=elevation,
                timestamp=timestamp,
                min_elevation=self.min_elevation
            )
            
            # Convert to Satellite objects
            satellites = []
            for data in sat_data:
                satellites.append(Satellite(
                    prn=data.get('prn', 'UNKNOWN'),
                    azimuth=data.get('azimuth', 0.0),
                    elevation=data.get('elevation', 0.0),
                    system=data.get('system', 'GPS')
                ))
            
            return satellites
            
        except Exception as e:
            logger.error(f"Error querying satellite engine: {e}")
            return []
    
    def _get_buildings_in_radius(
        self,
        lat: float,
        lon: float,
        radius_m: float
    ) -> List[Dict[str, Any]]:
        """
        Query the data pipeline for buildings within search radius.
        
        Args:
            lat: Center latitude
            lon: Center longitude
            radius_m: Search radius in meters
        
        Returns:
            List of building data dictionaries
        """
        try:
            buildings = self.data_pipeline.get_buildings_in_radius(
                lat=lat,
                lon=lon,
                radius_m=radius_m
            )
            return buildings
            
        except Exception as e:
            logger.error(f"Error querying building data: {e}")
            return []
    
    def _convert_buildings_to_enu(
        self,
        buildings: List[Dict[str, Any]],
        ref_lat: float,
        ref_lon: float,
        ref_elev: float
    ) -> np.ndarray:
        """
        Convert building positions to ENU coordinates relative to reference.
        
        Args:
            buildings: List of building dictionaries with lat/lon/height
            ref_lat: Reference latitude (user position)
            ref_lon: Reference longitude (user position)
            ref_elev: Reference elevation (user position)
        
        Returns:
            Structured numpy array with e, n, roof_height fields
        """
        if not buildings:
            return np.array([], dtype=[('e', float), ('n', float), ('roof_height', float)])
        
        # Extract building coordinates
        lats = np.array([b.get('lat', 0.0) for b in buildings])
        lons = np.array([b.get('lon', 0.0) for b in buildings])
        base_elevs = np.array([b.get('ground_elevation', 0.0) for b in buildings])
        heights = np.array([b.get('height', 0.0) for b in buildings])
        
        # Convert to ENU coordinates
        e, n, u = wgs84_to_enu(lats, lons, base_elevs, ref_lat, ref_lon, ref_elev)
        
        # Roof height is base elevation + building height (relative to user)
        roof_heights = base_elevs + heights
        
        # Create structured array
        dtype = [('e', float), ('n', float), ('roof_height', float)]
        result = np.zeros(len(buildings), dtype=dtype)
        result['e'] = e
        result['n'] = n
        result['roof_height'] = roof_heights
        
        return result
    
    def _get_blocked_azimuths(
        self,
        obstruction_profile: np.ndarray,
        satellites: List[Satellite]
    ) -> List[float]:
        """
        Get list of azimuth angles where LOS is blocked for at least one satellite.
        
        This identifies the specific directions where buildings would block
        satellite signals, useful for visualization and user guidance.
        
        Args:
            obstruction_profile: Array of max obstruction elevation per sector
            satellites: List of visible satellites
        
        Returns:
            List of azimuth angles (degrees) where LOS is blocked
        """
        blocked_sectors = set()
        
        for sat in satellites:
            sector_idx = azimuth_to_sector_index(sat.azimuth, self.sector_width)
            obstruction_elev = obstruction_profile[sector_idx]
            
            if sat.elevation <= obstruction_elev:
                # This satellite is blocked - mark the sector
                blocked_sectors.add(sector_idx)
        
        # Also include sectors with high obstruction even if no satellite there
        # This represents potential blockage for future satellite positions
        for sector_idx, obstruction_elev in enumerate(obstruction_profile):
            if obstruction_elev > self.min_elevation:
                blocked_sectors.add(sector_idx)
        
        # Convert sector indices to azimuth angles (center of each sector)
        blocked_azimuths = [
            sector_index_to_azimuth(int(s), self.sector_width)
            for s in sorted(blocked_sectors)
        ]
        
        return blocked_azimuths
    
    def batch_analyze(
        self,
        positions: List[Tuple[float, float, float]],
        timestamp: Optional[datetime] = None,
        radius_m: float = 500.0
    ) -> List[AnalysisResult]:
        """
        Analyze multiple positions in batch.
        
        This is more efficient than calling analyze_position repeatedly
        because it can reuse satellite visibility calculations for nearby
        positions (satellite positions change slowly over small distances).
        
        Args:
            positions: List of (lat, lon, elevation) tuples
            timestamp: Analysis timestamp (default: current UTC)
            radius_m: Search radius for buildings
        
        Returns:
            List of AnalysisResult objects (same order as input)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        results = []
        for lat, lon, elevation in positions:
            result = self.analyze_position(lat, lon, elevation, timestamp, radius_m)
            results.append(result)
        
        return results


class MockSatelliteEngine:
    """
    Mock satellite engine for testing without real ephemeris data.
    
    Generates synthetic satellite positions for testing the obstruction engine.
    """
    
    def __init__(self, n_satellites: int = 12):
        self.n_satellites = n_satellites
    
    def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation: float,
        timestamp: datetime,
        min_elevation: float = 25.0
    ) -> List[Dict[str, Any]]:
        """Generate mock satellite data for testing."""
        import random
        random.seed(int(lat * 10000 + lon * 100))
        
        satellites = []
        for i in range(self.n_satellites):
            # Generate random but deterministic positions
            azimuth = (i * 30 + random.uniform(-10, 10)) % 360
            elevation = random.uniform(min_elevation, 85)
            
            satellites.append({
                'prn': f'G{i+1:02d}',
                'azimuth': azimuth,
                'elevation': elevation,
                'system': 'GPS'
            })
        
        return satellites


class MockDataPipeline:
    """
    Mock data pipeline for testing without real building data.
    
    Generates synthetic building data for testing the obstruction engine.
    """
    
    def __init__(self, n_buildings: int = 50):
        self.n_buildings = n_buildings
    
    def get_buildings_in_radius(
        self,
        lat: float,
        lon: float,
        radius_m: float
    ) -> List[Dict[str, Any]]:
        """Generate mock building data for testing."""
        import random
        import math
        random.seed(int(lat * 10000 + lon * 100))
        
        buildings = []
        for i in range(self.n_buildings):
            # Random position within radius
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(10, radius_m)
            
            # Convert to approximate lat/lon offset
            # 1 degree latitude ≈ 111km, 1 degree longitude varies
            lat_offset = (distance * math.cos(angle)) / 111000
            lon_offset = (distance * math.sin(angle)) / (111000 * math.cos(math.radians(lat)))
            
            building_lat = lat + lat_offset
            building_lon = lon + lon_offset
            
            buildings.append({
                'lat': building_lat,
                'lon': building_lon,
                'ground_elevation': random.uniform(-5, 5),
                'height': random.uniform(5, 80),
                'footprint_area': random.uniform(50, 500)
            })
        
        return buildings
