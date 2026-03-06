"""Parsing helpers for two-line element catalogs."""

from __future__ import annotations

from datetime import datetime

from .time import tle_epoch_to_datetime
from .types import TleRecord


def _parse_implied_decimal(token: str) -> float:
    cleaned = token.strip()
    if not cleaned:
        return 0.0

    mantissa = cleaned[:-2].strip()
    exponent = cleaned[-2:].strip()
    if not mantissa:
        return 0.0

    sign = -1.0 if mantissa.startswith("-") else 1.0
    mantissa_digits = mantissa.lstrip("+-").strip()
    if not mantissa_digits:
        return 0.0

    return sign * float(f"0.{mantissa_digits}") * (10.0 ** int(exponent))


def parse_tle_record(name: str, line1: str, line2: str) -> TleRecord:
    """Parse a single three-line TLE record."""
    line1 = line1.rstrip()
    line2 = line2.rstrip()
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        raise ValueError("Invalid TLE lines")

    satellite_id = line1[2:7].strip()
    norad_id = int(satellite_id) if satellite_id.isdigit() else None
    epoch = tle_epoch_to_datetime(line1[18:32])
    eccentricity = float(f"0.{line2[26:33].strip() or '0'}")

    return TleRecord(
        name=name.strip() or f"SATELLITE {satellite_id or 'UNKNOWN'}",
        line1=line1,
        line2=line2,
        satellite_id=satellite_id or "UNKNOWN",
        norad_id=norad_id,
        epoch_utc=epoch,
        inclination_deg=float(line2[8:16]),
        raan_deg=float(line2[17:25]),
        eccentricity=eccentricity,
        argument_of_perigee_deg=float(line2[34:42]),
        mean_anomaly_deg=float(line2[43:51]),
        mean_motion_rev_per_day=float(line2[52:63]),
        bstar=_parse_implied_decimal(line1[53:61]),
    )


def parse_tle_catalog(payload: str) -> list[TleRecord]:
    """Parse mixed 2-line or 3-line TLE payloads into records."""
    records: list[TleRecord] = []
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    index = 0

    while index < len(lines):
        current = lines[index]

        if (
            current.startswith("1 ")
            and index + 1 < len(lines)
            and lines[index + 1].startswith("2 ")
        ):
            line1 = current
            line2 = lines[index + 1]
            sat_id = line1[2:7].strip() or "UNKNOWN"
            records.append(parse_tle_record(f"SATELLITE {sat_id}", line1, line2))
            index += 2
            continue

        if (
            index + 2 < len(lines)
            and lines[index + 1].startswith("1 ")
            and lines[index + 2].startswith("2 ")
        ):
            records.append(parse_tle_record(lines[index], lines[index + 1], lines[index + 2]))
            index += 3
            continue

        index += 1

    if not records:
        raise ValueError("No valid TLE records found")
    return records
