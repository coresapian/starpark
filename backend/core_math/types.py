"""Typed runtime records for LinkSpot math and orbit services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GeodesicResult:
    """Distance and bearings between two geodetic points."""

    distance_m: float
    initial_bearing_deg: float
    final_bearing_deg: float


@dataclass(frozen=True)
class TleRecord:
    """Parsed TLE record with derived metadata used by runtime services."""

    name: str
    line1: str
    line2: str
    satellite_id: str
    norad_id: int | None
    epoch_utc: datetime
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    argument_of_perigee_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float
    bstar: float


@dataclass(frozen=True)
class PropagatedState:
    """Satellite state after propagation and frame conversion."""

    x_ecef_m: float
    y_ecef_m: float
    z_ecef_m: float
    vx_ecef_m_s: float
    vy_ecef_m_s: float
    vz_ecef_m_s: float
    latitude_deg: float
    longitude_deg: float
    altitude_m: float


@dataclass(frozen=True)
class TemeState:
    """TEME state vector produced directly by the in-repo SGP4 core."""

    x_km: float
    y_km: float
    z_km: float
    vx_km_s: float
    vy_km_s: float
    vz_km_s: float


@dataclass(frozen=True)
class TopocentricObservation:
    """Observer-relative satellite state for API responses."""

    satellite_id: str
    norad_id: int | None
    name: str
    azimuth_deg: float
    elevation_deg: float
    slant_range_km: float
    latitude_deg: float
    longitude_deg: float
    altitude_km: float
    velocity_km_s: float | None
    is_visible: bool
