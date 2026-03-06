"""Focused tests for LinkSpot's canonical math package."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from core_math import (
    OrbitCatalog,
    datetime_to_julian_parts,
    ecef_to_geodetic,
    enu_to_geodetic,
    geodetic_to_ecef,
    geodetic_to_enu,
    parse_tle_record,
    parse_tle_catalog,
    propagate_tle_teme,
    vincenty_direct,
    vincenty_inverse,
)


FIXTURES_DIR = Path(__file__).parent / "test_fixtures" / "core_math"


class TestCanonicalTime(unittest.TestCase):
    def test_j2000_julian_epoch(self) -> None:
        jd, frac = datetime_to_julian_parts(
            datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(jd, 2451545.0)
        self.assertAlmostEqual(frac, 0.0, places=12)


class TestCanonicalGeodesy(unittest.TestCase):
    def test_known_ecef_reference_points(self) -> None:
        fixtures = json.loads((FIXTURES_DIR / "geodesy_cases.json").read_text())
        for fixture in fixtures:
            x_m, y_m, z_m = geodetic_to_ecef(
                fixture["lat_deg"],
                fixture["lon_deg"],
                fixture["altitude_m"],
            )
            exp_x, exp_y, exp_z = fixture["expected_ecef_m"]
            self.assertAlmostEqual(x_m, exp_x, places=3, msg=fixture["name"])
            self.assertAlmostEqual(y_m, exp_y, places=3, msg=fixture["name"])
            self.assertAlmostEqual(z_m, exp_z, places=3, msg=fixture["name"])

    def test_geodetic_roundtrip(self) -> None:
        points = [
            (40.7128, -74.0060, 10.0),
            (0.0, 179.9, 0.0),
            (89.9, 45.0, 500.0),
        ]
        for lat_deg, lon_deg, altitude_m in points:
            x_m, y_m, z_m = geodetic_to_ecef(lat_deg, lon_deg, altitude_m)
            back_lat, back_lon, back_alt = ecef_to_geodetic(x_m, y_m, z_m)
            self.assertAlmostEqual(back_lat, lat_deg, places=7)
            self.assertAlmostEqual(back_lon, lon_deg, places=7)
            self.assertAlmostEqual(back_alt, altitude_m, places=3)

    def test_enu_roundtrip_and_antimeridian(self) -> None:
        ref = (0.0, 179.9, 0.0)
        point = (0.0, -179.9, 0.0)
        east_m, north_m, up_m = geodetic_to_enu(*point, *ref)
        self.assertLess((east_m ** 2 + north_m ** 2) ** 0.5, 50000.0)

        back_lat, back_lon, back_alt = enu_to_geodetic(
            east_m, north_m, up_m, *ref
        )
        self.assertAlmostEqual(back_lat, point[0], places=4)
        self.assertAlmostEqual(back_lon, point[1], places=4)
        self.assertAlmostEqual(back_alt, point[2], places=2)

    def test_vincenty_inverse_direct_consistency(self) -> None:
        result = vincenty_inverse(39.7392, -104.9903, 40.0150, -105.2705)
        out_lat, out_lon, _ = vincenty_direct(
            39.7392,
            -104.9903,
            result.initial_bearing_deg,
            result.distance_m,
        )
        self.assertAlmostEqual(out_lat, 40.0150, places=4)
        self.assertAlmostEqual(out_lon, -105.2705, places=4)


class TestCanonicalTleAndOrbit(unittest.TestCase):
    def test_parse_tle_catalog(self) -> None:
        records = parse_tle_catalog((FIXTURES_DIR / "starlink_sample.tle").read_text())
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0].name, "STARLINK-1007")
        self.assertEqual(records[0].satellite_id, "44713")
        self.assertEqual(records[0].epoch_utc.year, 2024)
        self.assertAlmostEqual(records[0].inclination_deg, 53.0, places=3)
        self.assertAlmostEqual(records[0].mean_motion_rev_per_day, 15.5, places=6)

    def test_orbit_catalog_observation_shape(self) -> None:
        records = parse_tle_catalog((FIXTURES_DIR / "starlink_sample.tle").read_text())
        catalog = OrbitCatalog(records=records)
        observations = catalog.observe(
            observer_lat_deg=39.7392,
            observer_lon_deg=-104.9903,
            observer_altitude_m=1609.0,
            when_utc=datetime(2024, 12, 24, 12, 0, 0, tzinfo=timezone.utc),
            min_elevation_deg=-90.0,
        )
        self.assertEqual(len(observations), 4)
        for observation in observations:
            self.assertGreaterEqual(observation.azimuth_deg, 0.0)
            self.assertLess(observation.azimuth_deg, 360.0)
            self.assertGreaterEqual(observation.elevation_deg, -90.0)
            self.assertLessEqual(observation.elevation_deg, 90.0)
            self.assertGreater(observation.slant_range_km, 0.0)

    def test_near_earth_sgp4_matches_vallado_reference_vectors(self) -> None:
        fixture = json.loads((FIXTURES_DIR / "sgp4_reference_case.json").read_text())
        record = parse_tle_record(
            fixture["name"],
            fixture["line1"],
            fixture["line2"],
        )

        for sample in fixture["samples"]:
            when_utc = record.epoch_utc + timedelta(minutes=sample["tsince_minutes"])
            state = propagate_tle_teme(record, when_utc)
            expected_position = sample["position_km"]
            expected_velocity = sample["velocity_km_s"]
            self.assertAlmostEqual(state.x_km, expected_position[0], places=3)
            self.assertAlmostEqual(state.y_km, expected_position[1], places=3)
            self.assertAlmostEqual(state.z_km, expected_position[2], places=3)
            self.assertAlmostEqual(state.vx_km_s, expected_velocity[0], places=6)
            self.assertAlmostEqual(state.vy_km_s, expected_velocity[1], places=6)
            self.assertAlmostEqual(state.vz_km_s, expected_velocity[2], places=6)

    def test_deep_space_sgp4_matches_vallado_reference_vectors(self) -> None:
        fixtures = json.loads((FIXTURES_DIR / "sgp4_deep_space_cases.json").read_text())
        for fixture in fixtures:
            record = parse_tle_record(
                fixture["name"],
                fixture["line1"],
                fixture["line2"],
            )
            for sample in fixture["samples"]:
                when_utc = record.epoch_utc + timedelta(
                    minutes=sample["tsince_minutes"]
                )
                state = propagate_tle_teme(record, when_utc)
                expected_position = sample["position_km"]
                expected_velocity = sample["velocity_km_s"]
                self.assertAlmostEqual(
                    state.x_km,
                    expected_position[0],
                    places=3,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
                self.assertAlmostEqual(
                    state.y_km,
                    expected_position[1],
                    places=3,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
                self.assertAlmostEqual(
                    state.z_km,
                    expected_position[2],
                    places=3,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
                self.assertAlmostEqual(
                    state.vx_km_s,
                    expected_velocity[0],
                    places=6,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
                self.assertAlmostEqual(
                    state.vy_km_s,
                    expected_velocity[1],
                    places=6,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
                self.assertAlmostEqual(
                    state.vz_km_s,
                    expected_velocity[2],
                    places=6,
                    msg=f'{fixture["name"]} @ {sample["tsince_minutes"]} min',
                )
