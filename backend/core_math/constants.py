"""Canonical mathematical constants for LinkSpot runtime calculations."""

from __future__ import annotations

import math

WGS84_A_M = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B_M = WGS84_A_M * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
WGS84_EP2 = WGS84_E2 / (1.0 - WGS84_E2)

EARTH_MEAN_RADIUS_M = 6371008.8
EARTH_ROTATION_RATE_RAD_S = 7.2921150e-5

DEG_TO_RAD = math.pi / 180.0
RAD_TO_DEG = 180.0 / math.pi

SECONDS_PER_DAY = 86400.0
JULIAN_DAY_UNIX_EPOCH = 2440587.5
