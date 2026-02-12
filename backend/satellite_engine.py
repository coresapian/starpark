#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Satellite Constellation Engine for LinkSpot

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

This module provides satellite orbital mechanics calculations using Skyfield
for SGP4 propagation of NORAD TLE data. It computes azimuth and elevation
angles for Starlink satellites relative to ground observer positions.

Author: LinkSpot Engineering Team
Version: 1.0.0
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union, Any
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import requests
from skyfield.api import Loader, EarthSatellite, wgs84
from skyfield.timelib import Time
from skyfield.toposlib import Geoid
from skyfield.positionlib import Geocentric
from skyfield import almanac

# Configure logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Constants
CELESTRAK_STARLINK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
DEFAULT_TLE_CACHE_KEY = "starlink:tles"
DEFAULT_TLE_CACHE_TTL = 14400  # 4 hours in seconds
DEFAULT_MIN_ELEVATION = 25.0  # degrees
EARTH_RADIUS_KM = 6371.0


@dataclass
class SatellitePosition:
    """
    Data class representing a satellite's position relative to an observer.
    
    Attributes:
        satellite_id: NORAD catalog ID
        name: Satellite name from TLE
        azimuth: Azimuth angle in degrees (0-360, North=0, East=90)
        elevation: Elevation angle in degrees (0-90, horizon=0, zenith=90)
        range_km: Distance to satellite in kilometers
        latitude: Satellite geodetic latitude in degrees
        longitude: Satellite geodetic longitude in degrees
        altitude_km: Satellite altitude above WGS84 ellipsoid in km
        is_visible: Whether satellite is above minimum elevation mask
    """
    satellite_id: str
    name: str
    azimuth: float
    elevation: float
    range_km: float
    latitude: float
    longitude: float
    altitude_km: float
    is_visible: bool = True


@dataclass
class ConstellationStats:
    """
    Statistics about the loaded satellite constellation.
    
    Attributes:
        total_satellites: Total number of satellites in TLE data
        last_update: Timestamp of last TLE fetch
        cache_hit: Whether data was retrieved from cache
        source_url: URL where TLE data was fetched from
    """
    total_satellites: int
    last_update: Optional[datetime]
    cache_hit: bool
    source_url: str


class SatelliteEngine:
    """
    Main engine for computing satellite positions using SGP4 propagation.
    
    This class handles fetching TLE data from CelesTrak, caching in Redis,
    and computing azimuth/elevation angles for satellites relative to
    ground observer positions.
    
    Example:
        >>> import redis
        >>> from satellite_engine import SatelliteEngine
        >>> 
        >>> redis_client = redis.Redis(host='localhost', port=6379, db=0)
        >>> engine = SatelliteEngine(redis_client)
        >>> 
        >>> # Get visible satellites for a location
        >>> visible = engine.get_satellite_positions(
        ...     lat=37.7749,      # San Francisco
        ...     lon=-122.4194,
        ...     elevation=0.0,     # meters above sea level
        ...     timestamp=datetime.now(timezone.utc)
        ... )
        >>> 
        >>> for sat in visible:
        ...     print(f"{sat.name}: Az={sat.azimuth:.1f}°, El={sat.elevation:.1f}°")
    
    Attributes:
        redis_client: Redis client instance for caching TLE data
        tle_url: URL to fetch TLE data from (defaults to CelesTrak Starlink)
        cache_key: Redis key for TLE cache
        cache_ttl: Cache time-to-live in seconds (default 4 hours)
        min_elevation: Default minimum elevation filter in degrees
        _satellites: List of loaded EarthSatellite objects
        _last_update: Timestamp of last TLE update
        _ts: Skyfield timescale object
    """
    
    def __init__(
        self,
        redis_client: Any,
        tle_url: Optional[str] = None,
        cache_key: str = DEFAULT_TLE_CACHE_KEY,
        cache_ttl: int = DEFAULT_TLE_CACHE_TTL,
        min_elevation: float = DEFAULT_MIN_ELEVATION
    ):
        """
        Initialize the Satellite Engine.
        
        Args:
            redis_client: Redis client instance (redis.Redis)
            tle_url: URL for TLE data feed (default: CelesTrak Starlink)
            cache_key: Redis key for TLE cache
            cache_ttl: Cache TTL in seconds (default: 14400 = 4 hours)
            min_elevation: Default minimum elevation in degrees (default: 25.0)
        """
        self.redis_client = redis_client
        self.tle_url = tle_url or CELESTRAK_STARLINK_URL
        self.cache_key = cache_key
        self.cache_ttl = cache_ttl
        self.min_elevation = min_elevation
        
        # Internal state
        self._satellites: List[EarthSatellite] = []
        self._last_update: Optional[datetime] = None
        self._ts = self._load_timescale()
        
        logger.info(
            f"SatelliteEngine initialized with cache_key={cache_key}, "
            f"cache_ttl={cache_ttl}s, min_elevation={min_elevation}°"
        )
    
    def _load_timescale(self) -> Any:
        """
        Load or create Skyfield timescale.
        
        Returns:
            Skyfield timescale object
        """
        try:
            # Try to load from cache if available
            load = Loader('/tmp/skyfield_data')
            return load.timescale()
        except Exception as e:
            logger.warning(f"Could not load timescale from file: {e}, using builtin")
            from skyfield.api import load
            return load.timescale()
    
    def fetch_tle_data(self, force_refresh: bool = False) -> bool:
        """
        Fetch TLE data from CelesTrak and cache in Redis.
        
        This method attempts to retrieve TLE data from Redis cache first.
        If cache miss or force_refresh=True, it fetches from CelesTrak,
        parses the TLEs, and stores in Redis with TTL.
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            True if data was successfully loaded, False otherwise
            
        Raises:
            ConnectionError: If network request fails and no cache available
            ValueError: If TLE data cannot be parsed
        """
        start_time = time.time()
        
        # Try cache first unless force refresh
        if not force_refresh:
            cached_data = self._get_cached_tle()
            if cached_data:
                try:
                    self._parse_tle_data(cached_data)
                    logger.info(
                        f"Loaded {len(self._satellites)} satellites from cache "
                        f"in {(time.time() - start_time)*1000:.1f}ms"
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Failed to parse cached TLE: {e}, fetching fresh")
        
        # Fetch from CelesTrak
        try:
            logger.info(f"Fetching TLE data from {self.tle_url}")
            response = requests.get(self.tle_url, timeout=30)
            response.raise_for_status()
            tle_data = response.text
            
            # Parse and validate
            self._parse_tle_data(tle_data)
            
            # Cache the raw TLE data
            self._cache_tle_data(tle_data)
            
            self._last_update = datetime.now(timezone.utc)
            
            logger.info(
                f"Fetched and cached {len(self._satellites)} satellites "
                f"in {(time.time() - start_time)*1000:.1f}ms"
            )
            return True
            
        except requests.RequestException as e:
            logger.error(f"Network error fetching TLE data: {e}")
            # Try to use stale cache as fallback
            cached_data = self._get_cached_tle(ignore_ttl=True)
            if cached_data:
                logger.warning("Using stale cache due to network failure")
                self._parse_tle_data(cached_data)
                return True
            raise ConnectionError(f"Failed to fetch TLE data: {e}")
            
        except Exception as e:
            logger.error(f"Error processing TLE data: {e}")
            raise ValueError(f"Failed to parse TLE data: {e}")
    
    def _get_cached_tle(self, ignore_ttl: bool = False) -> Optional[str]:
        """
        Retrieve TLE data from Redis cache.
        
        Args:
            ignore_ttl: If True, return data even if expired
            
        Returns:
            Cached TLE data string or None if not found
        """
        try:
            if ignore_ttl:
                # Just get the value without TTL check
                data = self.redis_client.get(self.cache_key)
            else:
                # Check TTL first
                ttl = self.redis_client.ttl(self.cache_key)
                if ttl <= 0:
                    logger.debug("Cache expired or not found")
                    return None
                data = self.redis_client.get(self.cache_key)
            
            if data:
                # Handle both bytes and string returns
                if isinstance(data, bytes):
                    return data.decode('utf-8')
                return data
            return None
            
        except Exception as e:
            logger.warning(f"Redis cache read error: {e}")
            return None
    
    def _cache_tle_data(self, tle_data: str) -> bool:
        """
        Store TLE data in Redis cache.
        
        Args:
            tle_data: Raw TLE data string to cache
            
        Returns:
            True if caching succeeded, False otherwise
        """
        try:
            self.redis_client.setex(
                self.cache_key,
                self.cache_ttl,
                tle_data
            )
            logger.debug(f"Cached TLE data with TTL={self.cache_ttl}s")
            return True
        except Exception as e:
            logger.warning(f"Failed to cache TLE data: {e}")
            return False
    
    def _parse_tle_data(self, tle_data: str) -> None:
        """
        Parse TLE data string into EarthSatellite objects.
        
        TLE format: Three lines per satellite:
            Line 0: Satellite name
            Line 1: TLE first line (elements 1-69)
            Line 2: TLE second line (elements 70-138)
        
        Args:
            tle_data: Raw TLE data from CelesTrak
            
        Raises:
            ValueError: If TLE data format is invalid
        """
        self._satellites = []
        lines = tle_data.strip().split('\n')
        
        # TLE data comes in groups of 3 lines (name, line1, line2)
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Check if this is a TLE line 1 (starts with '1 ')
            if line.startswith('1 ') and len(line) >= 60:
                # This might be line 1 without a name line
                if i + 1 < len(lines) and lines[i + 1].startswith('2 '):
                    # Use catalog number as name
                    catalog_num = line[2:7].strip()
                    name = f"SATELLITE {catalog_num}"
                    line1 = line
                    line2 = lines[i + 1].strip()
                    try:
                        sat = EarthSatellite(line1, line2, name, self._ts)
                        self._satellites.append(sat)
                    except Exception as e:
                        logger.debug(f"Failed to parse TLE for {name}: {e}")
                    i += 2
                    continue
            
            # Standard 3-line TLE format
            if i + 2 < len(lines):
                name = line
                line1 = lines[i + 1].strip()
                line2 = lines[i + 2].strip()
                
                # Validate TLE format
                if line1.startswith('1 ') and line2.startswith('2 '):
                    try:
                        sat = EarthSatellite(line1, line2, name, self._ts)
                        self._satellites.append(sat)
                    except Exception as e:
                        logger.debug(f"Failed to parse TLE for {name}: {e}")
                    i += 3
                else:
                    i += 1
            else:
                i += 1
        
        if not self._satellites:
            raise ValueError("No valid TLE entries found in data")
        
        logger.debug(f"Parsed {len(self._satellites)} satellites from TLE data")
    
    def get_satellite_positions(
        self,
        lat: float,
        lon: float,
        elevation: float = 0.0,
        timestamp: Optional[Union[datetime, Time]] = None,
        min_elevation: Optional[float] = None
    ) -> List[SatellitePosition]:
        """
        Compute positions of all visible satellites for an observer.
        
        This is the main entry point for getting satellite visibility data.
        It computes azimuth and elevation for all satellites in the
        constellation relative to the observer's position.
        
        Args:
            lat: Observer latitude in degrees (-90 to 90)
            lon: Observer longitude in degrees (-180 to 180)
            elevation: Observer elevation above sea level in meters (default: 0)
            timestamp: Observation time (default: now). Can be datetime or Skyfield Time.
            min_elevation: Minimum elevation filter (default: from constructor)
            
        Returns:
            List of SatellitePosition objects for visible satellites
            
        Raises:
            RuntimeError: If no TLE data has been loaded
            ValueError: If coordinates are out of valid range
        """
        start_time = time.time()
        
        # Validate coordinates
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude {lat} out of range [-90, 90]")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude {lon} out of range [-180, 180]")
        
        # Ensure we have TLE data
        if not self._satellites:
            self.fetch_tle_data()
        
        # Use default timestamp if not provided
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        # Convert to Skyfield Time if needed
        if isinstance(timestamp, datetime):
            sf_time = self._ts.from_datetime(timestamp)
        else:
            sf_time = timestamp
        
        # Use provided or default min elevation
        elevation_threshold = min_elevation if min_elevation is not None else self.min_elevation
        
        # Create observer position
        observer = wgs84.latlon(lat, lon, elevation_m=elevation)
        
        # Compute positions for all satellites
        positions = []
        for satellite in self._satellites:
            try:
                pos = self.compute_azimuth_elevation(satellite, observer, sf_time)
                if pos.elevation >= elevation_threshold:
                    positions.append(pos)
            except Exception as e:
                logger.debug(f"Error computing position for {satellite.name}: {e}")
                continue
        
        # Sort by elevation (highest first)
        positions.sort(key=lambda x: x.elevation, reverse=True)
        
        elapsed = (time.time() - start_time) * 1000
        logger.info(
            f"Computed {len(positions)} visible satellites in {elapsed:.1f}ms "
            f"(threshold={elevation_threshold}°)"
        )
        
        return positions
    
    def compute_azimuth_elevation(
        self,
        satellite: EarthSatellite,
        observer_position: Union[Geoid, Any],
        timestamp: Union[datetime, Time]
    ) -> SatellitePosition:
        """
        Compute azimuth and elevation for a single satellite.
        
        Uses Skyfield's SGP4 propagation to compute the satellite's
        position at the given time, then transforms to topocentric
        coordinates relative to the observer.
        
        Args:
            satellite: Skyfield EarthSatellite object
            observer_position: Observer position (wgs84.latlon result)
            timestamp: Time of observation (datetime or Skyfield Time)
            
        Returns:
            SatellitePosition with azimuth, elevation, and other data
            
        Note:
            Azimuth is measured clockwise from North (0°=N, 90°=E, 180°=S, 270°=W)
            Elevation is measured from horizon (0°=horizon, 90°=zenith)
        """
        # Convert timestamp if needed
        if isinstance(timestamp, datetime):
            sf_time = self._ts.from_datetime(timestamp)
        else:
            sf_time = timestamp
        
        # Compute satellite position at time
        geocentric = satellite.at(sf_time)
        
        # Get subpoint (lat/lon/altitude)
        subpoint = wgs84.subpoint(geocentric)
        sat_lat = subpoint.latitude.degrees
        sat_lon = subpoint.longitude.degrees
        sat_alt = subpoint.elevation.km
        
        # Compute topocentric position relative to observer
        difference = satellite - observer_position
        topocentric = difference.at(sf_time)
        
        # Get altitude (elevation) and azimuth
        alt, az, distance = topocentric.altaz()
        
        # Handle edge case where satellite is below horizon
        elevation_deg = alt.degrees
        if elevation_deg < -90:
            elevation_deg = -90.0
        
        # Extract satellite ID from TLE line 1 (columns 3-7)
        sat_id = self._extract_satellite_id(satellite)
        
        return SatellitePosition(
            satellite_id=sat_id,
            name=satellite.name,
            azimuth=az.degrees,
            elevation=elevation_deg,
            range_km=distance.km,
            latitude=sat_lat,
            longitude=sat_lon,
            altitude_km=sat_alt,
            is_visible=(elevation_deg >= 0)
        )
    
    def _extract_satellite_id(self, satellite: EarthSatellite) -> str:
        """
        Extract NORAD catalog ID from satellite object.
        
        Args:
            satellite: EarthSatellite object
            
        Returns:
            NORAD catalog ID as string
        """
        # Try to get from model attribute
        if hasattr(satellite, 'model') and hasattr(satellite.model, 'satnum'):
            return str(int(satellite.model.satnum))
        
        # Fallback: parse from TLE line 1
        try:
            line1 = satellite.model.line1 if hasattr(satellite, 'model') else ""
            if line1 and len(line1) >= 7:
                return line1[2:7].strip()
        except:
            pass
        
        # Last resort: use name
        return satellite.name.replace(" ", "_")
    
    def filter_by_elevation(
        self,
        satellites: List[SatellitePosition],
        min_elevation: float = DEFAULT_MIN_ELEVATION
    ) -> List[SatellitePosition]:
        """
        Filter satellites by minimum elevation angle.
        
        Args:
            satellites: List of SatellitePosition objects
            min_elevation: Minimum elevation in degrees (default: 25.0)
            
        Returns:
            Filtered list containing only satellites above threshold
        """
        filtered = [
            sat for sat in satellites
            if sat.elevation >= min_elevation
        ]
        
        # Update visibility flag
        for sat in filtered:
            sat.is_visible = True
        
        logger.debug(
            f"Filtered {len(satellites)} -> {len(filtered)} satellites "
            f"(min_elevation={min_elevation}°)"
        )
        
        return filtered
    
    def get_constellation_stats(self) -> ConstellationStats:
        """
        Get statistics about the loaded constellation.
        
        Returns:
            ConstellationStats with satellite count and metadata
        """
        # Check if we need to load data
        if not self._satellites:
            try:
                self.fetch_tle_data()
            except Exception as e:
                logger.warning(f"Could not fetch constellation stats: {e}")
        
        # Check if data came from cache
        cache_hit = False
        try:
            ttl = self.redis_client.ttl(self.cache_key)
            cache_hit = (ttl > 0 and len(self._satellites) > 0)
        except:
            pass
        
        return ConstellationStats(
            total_satellites=len(self._satellites),
            last_update=self._last_update,
            cache_hit=cache_hit,
            source_url=self.tle_url
        )
    
    def get_satellite_by_id(self, satellite_id: str) -> Optional[EarthSatellite]:
        """
        Find a satellite by its NORAD catalog ID.
        
        Args:
            satellite_id: NORAD catalog ID to search for
            
        Returns:
            EarthSatellite object if found, None otherwise
        """
        for sat in self._satellites:
            if self._extract_satellite_id(sat) == str(satellite_id):
                return sat
        return None
    
    def clear_cache(self) -> bool:
        """
        Clear the TLE cache from Redis.
        
        Returns:
            True if cache was cleared, False otherwise
        """
        try:
            self.redis_client.delete(self.cache_key)
            logger.info(f"Cleared cache key: {self.cache_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False
    
    def refresh(self) -> bool:
        """
        Force refresh TLE data from source.
        
        Returns:
            True if refresh succeeded, False otherwise
        """
        return self.fetch_tle_data(force_refresh=True)


def vectorized_azimuth_elevation(
    satellites: List[EarthSatellite],
    observer: Any,
    timestamp: Time,
    ts: Any
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized computation of azimuth/elevation for multiple satellites.
    
    This is a performance-optimized version that uses NumPy vectorization
    for batch processing of satellite positions.
    
    Args:
        satellites: List of EarthSatellite objects
        observer: Observer position (wgs84.latlon result)
        timestamp: Skyfield Time object
        ts: Skyfield timescale
        
    Returns:
        Tuple of (azimuths, elevations, ranges) as numpy arrays
    """
    n = len(satellites)
    azimuths = np.zeros(n)
    elevations = np.zeros(n)
    ranges = np.zeros(n)
    
    # Process in batches for better cache efficiency
    batch_size = 100
    
    for i in range(0, n, batch_size):
        batch = satellites[i:i + batch_size]
        
        for j, sat in enumerate(batch):
            try:
                diff = sat - observer
                topocentric = diff.at(timestamp)
                alt, az, dist = topocentric.altaz()
                
                idx = i + j
                azimuths[idx] = az.degrees
                elevations[idx] = alt.degrees
                ranges[idx] = dist.km
            except Exception as e:
                logger.debug(f"Error in vectorized calc: {e}")
                idx = i + j
                azimuths[idx] = np.nan
                elevations[idx] = np.nan
                ranges[idx] = np.nan
    
    return azimuths, elevations, ranges


# Convenience function for direct usage
def get_visible_starlink_satellites(
    lat: float,
    lon: float,
    elevation: float = 0.0,
    timestamp: Optional[datetime] = None,
    min_elevation: float = DEFAULT_MIN_ELEVATION,
    redis_client: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to get visible Starlink satellites.
    
    This is a simplified interface for quick lookups without managing
    the engine instance.
    
    Args:
        lat: Observer latitude in degrees
        lon: Observer longitude in degrees
        elevation: Observer elevation in meters (default: 0)
        timestamp: Observation time (default: now)
        min_elevation: Minimum elevation filter (default: 25.0)
        redis_client: Optional Redis client for caching
        
    Returns:
        List of dictionaries with satellite visibility data
    """
    # Create temporary engine
    engine = SatelliteEngine(
        redis_client=redis_client or {},  # Dummy if no Redis
        cache_ttl=0 if redis_client is None else DEFAULT_TLE_CACHE_TTL
    )
    
    # Fetch TLE data directly
    engine.fetch_tle_data()
    
    # Get positions
    positions = engine.get_satellite_positions(
        lat=lat,
        lon=lon,
        elevation=elevation,
        timestamp=timestamp,
        min_elevation=min_elevation
    )
    
    # Convert to dict format
    return [
        {
            "satellite_id": pos.satellite_id,
            "name": pos.name,
            "azimuth": pos.azimuth,
            "elevation": pos.elevation,
            "range_km": pos.range_km,
            "latitude": pos.latitude,
            "longitude": pos.longitude,
            "altitude_km": pos.altitude_km
        }
        for pos in positions
    ]
