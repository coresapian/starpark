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


