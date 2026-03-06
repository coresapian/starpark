"""Time helpers for UTC normalization and Julian date conversion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from .constants import JULIAN_DAY_UNIX_EPOCH, RAD_TO_DEG, SECONDS_PER_DAY


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso8601_utc(value: str | None) -> datetime | None:
    """Parse an ISO 8601 value into UTC."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    normalized = normalized.replace("Z", "+00:00")
    return ensure_utc(datetime.fromisoformat(normalized))


def datetime_to_julian_parts(value: datetime) -> tuple[float, float]:
    """Convert a UTC datetime into whole and fractional Julian day parts."""
    utc_value = ensure_utc(value)
    unix_seconds = utc_value.timestamp()
    julian = JULIAN_DAY_UNIX_EPOCH + (unix_seconds / SECONDS_PER_DAY)
    whole = math.floor(julian)
    frac = julian - whole
    return float(whole), float(frac)


def julian_parts_to_datetime(jd: float, fraction: float) -> datetime:
    """Convert Julian day parts back into UTC datetime."""
    julian = float(jd) + float(fraction)
    unix_seconds = (julian - JULIAN_DAY_UNIX_EPOCH) * SECONDS_PER_DAY
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def gmst_radians(jd: float, fraction: float) -> float:
    """Compute Greenwich mean sidereal time in radians.

    The formula follows Vallado's expression for GMST using UT1-compatible
    Julian dates, which is sufficient for LinkSpot visibility planning.
    """

    jd_ut1 = float(jd) + float(fraction)
    t_ut1 = (jd_ut1 - 2451545.0) / 36525.0
    gmst_seconds = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t_ut1
        + 0.093104 * t_ut1 * t_ut1
        - 6.2e-6 * t_ut1 * t_ut1 * t_ut1
    )
    gmst_seconds %= SECONDS_PER_DAY
    return gmst_seconds * (2.0 * math.pi / SECONDS_PER_DAY)


def tle_epoch_to_datetime(epoch_token: str) -> datetime:
    """Convert a TLE epoch token like ``24358.50000000`` into UTC."""
    cleaned = epoch_token.strip()
    if len(cleaned) < 5:
        raise ValueError(f"Invalid TLE epoch token: {epoch_token}")

    year_short = int(cleaned[:2])
    year = 2000 + year_short if year_short < 57 else 1900 + year_short
    day_of_year = float(cleaned[2:])

    day_index = int(math.floor(day_of_year))
    fractional_day = day_of_year - day_index
    base = datetime(year, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(days=day_index - 1, seconds=fractional_day * SECONDS_PER_DAY)
