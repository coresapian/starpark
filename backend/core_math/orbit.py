"""Orbital observation helpers built around a canonical LinkSpot math core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .constants import EARTH_ROTATION_RATE_RAD_S
from .geodesy import (
    azimuth_from_enu,
    ecef_delta_to_enu,
    ecef_to_geodetic,
    elevation_from_enu,
    geodetic_to_ecef,
    slant_range_m_from_enu,
)
from .sgp4 import propagate_tle_teme
from .time import datetime_to_julian_parts
from .time import ensure_utc, gmst_radians
from .types import PropagatedState, TemeState, TleRecord, TopocentricObservation


def mean_motion_to_semimajor_axis_km(mean_motion_rev_per_day: float) -> float:
    """Convert mean motion in rev/day into semimajor axis in kilometers."""
    gravitational_parameter_km3_s2 = 398600.4418
    mean_motion_rad_s = float(mean_motion_rev_per_day) * (2.0 * math.pi / 86400.0)
    return (gravitational_parameter_km3_s2 / (mean_motion_rad_s ** 2)) ** (1.0 / 3.0)


def teme_to_ecef(
    position_km: tuple[float, float, float],
    velocity_km_s: tuple[float, float, float],
    when_utc: datetime,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Rotate TEME coordinates into an Earth-fixed frame using GMST."""
    jd, frac = datetime_to_julian_parts(ensure_utc(when_utc))
    theta = gmst_radians(jd, frac)
    sin_theta = math.sin(theta)
    cos_theta = math.cos(theta)

    px, py, pz = position_km
    vx, vy, vz = velocity_km_s

    x_pef_km = cos_theta * px + sin_theta * py
    y_pef_km = -sin_theta * px + cos_theta * py
    z_pef_km = pz

    vx_pef_km_s = cos_theta * vx + sin_theta * vy
    vy_pef_km_s = -sin_theta * vx + cos_theta * vy
    vz_pef_km_s = vz

    x_ecef_m = x_pef_km * 1000.0
    y_ecef_m = y_pef_km * 1000.0
    z_ecef_m = z_pef_km * 1000.0

    vx_ecef_m_s = (
        vx_pef_km_s * 1000.0 + EARTH_ROTATION_RATE_RAD_S * (-y_pef_km * 1000.0)
    )
    vy_ecef_m_s = (
        vy_pef_km_s * 1000.0 + EARTH_ROTATION_RATE_RAD_S * (x_pef_km * 1000.0)
    )
    vz_ecef_m_s = vz_pef_km_s * 1000.0

    return (
        (x_ecef_m, y_ecef_m, z_ecef_m),
        (vx_ecef_m_s, vy_ecef_m_s, vz_ecef_m_s),
    )


def propagate_tle(record: TleRecord, when_utc: datetime) -> PropagatedState:
    """Propagate a TLE to an Earth-fixed state."""
    teme_state = propagate_tle_teme(record, when_utc)
    (x_ecef_m, y_ecef_m, z_ecef_m), (vx_ecef_m_s, vy_ecef_m_s, vz_ecef_m_s) = teme_to_ecef(
        (teme_state.x_km, teme_state.y_km, teme_state.z_km),
        (teme_state.vx_km_s, teme_state.vy_km_s, teme_state.vz_km_s),
        when_utc,
    )
    latitude_deg, longitude_deg, altitude_m = ecef_to_geodetic(x_ecef_m, y_ecef_m, z_ecef_m)
    return PropagatedState(
        x_ecef_m=x_ecef_m,
        y_ecef_m=y_ecef_m,
        z_ecef_m=z_ecef_m,
        vx_ecef_m_s=vx_ecef_m_s,
        vy_ecef_m_s=vy_ecef_m_s,
        vz_ecef_m_s=vz_ecef_m_s,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        altitude_m=altitude_m,
    )


def propagate_tle_teme_state(record: TleRecord, when_utc: datetime) -> TemeState:
    """Propagate a TLE to a TEME state vector."""
    return propagate_tle_teme(record, when_utc)


def observe_tle(
    record: TleRecord,
    when_utc: datetime,
    observer_lat_deg: float,
    observer_lon_deg: float,
    observer_altitude_m: float,
) -> TopocentricObservation:
    """Observe a satellite from a WGS84 ground location."""
    state = propagate_tle(record, when_utc)
    obs_x_m, obs_y_m, obs_z_m = geodetic_to_ecef(
        observer_lat_deg,
        observer_lon_deg,
        observer_altitude_m,
    )

    east_m, north_m, up_m = ecef_delta_to_enu(
        state.x_ecef_m - obs_x_m,
        state.y_ecef_m - obs_y_m,
        state.z_ecef_m - obs_z_m,
        observer_lat_deg,
        observer_lon_deg,
    )
    velocity_km_s = math.sqrt(
        state.vx_ecef_m_s * state.vx_ecef_m_s
        + state.vy_ecef_m_s * state.vy_ecef_m_s
        + state.vz_ecef_m_s * state.vz_ecef_m_s
    ) / 1000.0

    azimuth_deg = azimuth_from_enu(east_m, north_m)
    elevation_deg = elevation_from_enu(east_m, north_m, up_m)
    slant_range_km = slant_range_m_from_enu(east_m, north_m, up_m) / 1000.0

    return TopocentricObservation(
        satellite_id=record.satellite_id,
        norad_id=record.norad_id,
        name=record.name,
        azimuth_deg=azimuth_deg,
        elevation_deg=elevation_deg,
        slant_range_km=slant_range_km,
        latitude_deg=state.latitude_deg,
        longitude_deg=state.longitude_deg,
        altitude_km=state.altitude_m / 1000.0,
        velocity_km_s=velocity_km_s,
        is_visible=elevation_deg >= 0.0,
    )


@dataclass
class OrbitCatalog:
    """In-memory TLE catalog for repeated observation queries."""

    records: list[TleRecord]

    def observe(
        self,
        observer_lat_deg: float,
        observer_lon_deg: float,
        observer_altitude_m: float,
        when_utc: datetime,
        min_elevation_deg: float | None = None,
    ) -> list[TopocentricObservation]:
        observations: list[TopocentricObservation] = []
        threshold = 0.0 if min_elevation_deg is None else float(min_elevation_deg)
        for record in self.records:
            try:
                observation = observe_tle(
                    record,
                    when_utc,
                    observer_lat_deg,
                    observer_lon_deg,
                    observer_altitude_m,
                )
            except Exception:
                continue
            if observation.elevation_deg >= threshold:
                observations.append(observation)
        observations.sort(key=lambda item: (item.elevation_deg, item.satellite_id), reverse=True)
        return observations

    def positions(
        self,
        when_utc: datetime,
        max_points: int | None = None,
    ) -> list[dict[str, float | str | int | None]]:
        positions: list[dict[str, float | str | int | None]] = []
        for record in self.records:
            try:
                state = propagate_tle(record, when_utc)
            except Exception:
                continue
            velocity_km_s = math.sqrt(
                state.vx_ecef_m_s * state.vx_ecef_m_s
                + state.vy_ecef_m_s * state.vy_ecef_m_s
                + state.vz_ecef_m_s * state.vz_ecef_m_s
            ) / 1000.0
            positions.append(
                {
                    "satellite_id": record.satellite_id,
                    "norad_id": record.norad_id,
                    "name": record.name,
                    "latitude": state.latitude_deg,
                    "longitude": state.longitude_deg,
                    "altitude_km": state.altitude_m / 1000.0,
                    "velocity_kms": velocity_km_s,
                }
            )
        positions.sort(key=lambda item: str(item.get("satellite_id") or ""))
        if max_points is not None and max_points > 0:
            positions = positions[:max_points]
        return positions
