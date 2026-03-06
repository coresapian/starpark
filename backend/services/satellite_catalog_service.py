"""Satellite catalog runtime using LinkSpot's canonical math package."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import json
import logging
import random
import time
from typing import Any

import requests

from core_math import OrbitCatalog, TleRecord, ensure_utc, mean_motion_to_semimajor_axis_km, parse_tle_catalog

logger = logging.getLogger(__name__)

CELESTRAK_STARLINK_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"
)
SPACE_TRACK_LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
SPACE_TRACK_STARLINK_GP_FULL_URL = (
    "https://www.space-track.org/basicspacedata/query/"
    "class/gp/OBJECT_NAME/STARLINK~~/DECAY_DATE/null-val/EPOCH/%3Enow-30/"
    "NORAD_CAT_ID/%3C100000/ORDERBY/NORAD_CAT_ID/format/3le/emptyresult/show"
)
SPACE_TRACK_STARLINK_GP_DELTA_URL = (
    "https://www.space-track.org/basicspacedata/query/"
    "class/gp/OBJECT_NAME/STARLINK~~/DECAY_DATE/null-val/"
    "CREATION_DATE/%3Enow-0.042/NORAD_CAT_ID/%3C100000/"
    "ORDERBY/NORAD_CAT_ID/format/3le/emptyresult/show"
)
DEFAULT_TLE_CACHE_KEY = "starlink:tles"
DEFAULT_TLE_CACHE_TTL = 14400


class SatelliteCatalogService:
    """Fetch, cache, and observe TLE catalogs through the canonical math core."""

    def __init__(
        self,
        redis_client: Any,
        tle_url: str | None = None,
        cache_key: str = DEFAULT_TLE_CACHE_KEY,
        cache_ttl: int = DEFAULT_TLE_CACHE_TTL,
        min_elevation_deg: float = 25.0,
        space_track_identity: str | None = None,
        space_track_password: str | None = None,
        space_track_min_interval_seconds: int = 3600,
        space_track_per_minute_limit: int = 30,
        space_track_per_hour_limit: int = 300,
        space_track_timeout_seconds: float = 30.0,
    ) -> None:
        self.redis_client = redis_client
        self.tle_url = tle_url or CELESTRAK_STARLINK_URL
        self.cache_key = cache_key
        self.cache_ttl = int(cache_ttl)
        self.min_elevation_deg = float(min_elevation_deg)
        self.space_track_identity = (space_track_identity or "").strip() or None
        self.space_track_password = space_track_password
        self.space_track_min_interval_seconds = max(60, int(space_track_min_interval_seconds))
        self.space_track_per_minute_limit = max(1, int(space_track_per_minute_limit))
        self.space_track_per_hour_limit = max(1, int(space_track_per_hour_limit))
        self.space_track_timeout_seconds = max(1.0, float(space_track_timeout_seconds))
        self._space_track_gate_cache_key = f"{cache_key}:space_track_next_fetch"
        self._space_track_query_timestamps: deque[float] = deque()
        self._space_track_next_fetch_ts = 0.0

        self._tle_source = "unknown"
        self._last_update: datetime | None = None
        self._records: list[TleRecord] = []
        self._catalog: OrbitCatalog | None = None
        self.is_degraded = False
        self.degraded_reason: str | None = None

    @property
    def last_update(self) -> datetime | None:
        return self._last_update

    @property
    def tle_source(self) -> str:
        return self._tle_source

    def fetch_tle_data(self, force_refresh: bool = False) -> bool:
        """Load a catalog from cache or network sources."""
        if not force_refresh and not self._catalog:
            cached_tle = self._get_cached_tle(ignore_ttl=False)
            if cached_tle:
                self._load_catalog(cached_tle)
                return True

        fetch_errors: list[str] = []

        if self.space_track_identity and self.space_track_password:
            if self._space_track_fetch_allowed(force_refresh=force_refresh):
                try:
                    cached_seed = self._get_cached_tle(ignore_ttl=True)
                    payload = self._refresh_space_track_tles(cached_seed)
                    self._tle_source = "space-track"
                    self._load_catalog(payload)
                    self._cache_tle_data(payload)
                    self._persist_space_track_gate(self._schedule_next_space_track_fetch_ts())
                    return True
                except Exception as exc:
                    fetch_errors.append(f"space-track: {exc}")
                    logger.warning("Space-Track fetch failed, falling back: %s", exc)

        try:
            payload = self._refresh_celestrak_tles()
            self._tle_source = "celestrak"
            self._load_catalog(payload)
            self._cache_tle_data(payload)
            return True
        except Exception as exc:
            fetch_errors.append(f"celestrak: {exc}")
            cached_tle = self._get_cached_tle(ignore_ttl=True)
            if cached_tle:
                logger.warning("Using stale TLE cache after fetch failure: %s", exc)
                if self._tle_source == "unknown":
                    self._tle_source = "cache_stale"
                self._load_catalog(cached_tle)
                return True

        self.is_degraded = True
        self.degraded_reason = "; ".join(fetch_errors) if fetch_errors else "tle_fetch_failed"
        raise ConnectionError(self.degraded_reason)

    def get_visible_satellites(
        self,
        lat: float,
        lon: float,
        elevation_m: float = 0.0,
        timestamp: datetime | None = None,
        min_elevation_deg: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return observer-relative visibility data."""
        self._ensure_catalog()
        assert self._catalog is not None

        when = ensure_utc(timestamp or datetime.now(timezone.utc))
        observations = self._catalog.observe(
            observer_lat_deg=lat,
            observer_lon_deg=lon,
            observer_altitude_m=elevation_m,
            when_utc=when,
            min_elevation_deg=self.min_elevation_deg if min_elevation_deg is None else min_elevation_deg,
        )
        return [
            {
                "satellite_id": item.satellite_id,
                "norad_id": item.norad_id,
                "name": item.name,
                "azimuth": item.azimuth_deg,
                "elevation": item.elevation_deg,
                "range_km": item.slant_range_km,
                "latitude": item.latitude_deg,
                "longitude": item.longitude_deg,
                "altitude_km": item.altitude_km,
                "velocity_kms": item.velocity_km_s,
                "constellation": self._constellation_name(),
                "is_visible": item.is_visible,
            }
            for item in observations
        ]

    def get_constellation_metadata(self) -> dict[str, Any]:
        """Summarize the currently loaded catalog."""
        self._ensure_catalog()
        if not self._records:
            return {
                "name": "Unknown",
                "operator": "Unknown",
                "total_satellites": 0,
                "active_satellites": 0,
                "orbital_planes": None,
                "altitude_km": None,
                "inclination_deg": None,
            }

        altitudes = []
        inclinations = []
        for record in self._records:
            inclinations.append(record.inclination_deg)
            try:
                altitudes.append(mean_motion_to_semimajor_axis_km(record.mean_motion_rev_per_day) - 6371.0)
            except Exception:
                continue

        return {
            "name": self._constellation_name(),
            "operator": self._constellation_operator(),
            "total_satellites": len(self._records),
            "active_satellites": len(self._records),
            "orbital_planes": None,
            "altitude_km": round(sum(altitudes) / len(altitudes), 1) if altitudes else None,
            "inclination_deg": round(sum(inclinations) / len(inclinations), 1) if inclinations else None,
        }

    def get_constellation_positions(
        self,
        timestamp: datetime | None = None,
        max_points: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return geodetic positions for map overlays."""
        self._ensure_catalog()
        assert self._catalog is not None

        when = ensure_utc(timestamp or datetime.now(timezone.utc))
        positions = self._catalog.positions(when_utc=when, max_points=max_points)
        for item in positions:
            item["constellation"] = self._constellation_name()
        return positions

    def health_snapshot(self) -> dict[str, Any]:
        """Expose a lightweight readiness view for health probes."""
        return {
            "loaded": bool(self._catalog and self._records),
            "source": self._tle_source,
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "degraded": self.is_degraded,
            "reason": self.degraded_reason,
            "count": len(self._records),
        }

    def _ensure_catalog(self) -> None:
        if self._catalog is None:
            self.fetch_tle_data(force_refresh=False)

    def _load_catalog(self, payload: str) -> None:
        self._records = parse_tle_catalog(payload)
        self._catalog = OrbitCatalog(records=self._records)
        if self._last_update is None:
            self._last_update = datetime.now(timezone.utc)
        self.is_degraded = False
        self.degraded_reason = None

    def _constellation_name(self) -> str:
        names = [record.name.upper() for record in self._records]
        if any("STARLINK" in name for name in names):
            return "Starlink"
        if any("ONEWEB" in name for name in names):
            return "OneWeb"
        if any("IRIDIUM" in name for name in names):
            return "Iridium"
        return "Unknown"

    def _constellation_operator(self) -> str:
        constellation = self._constellation_name()
        if constellation == "Starlink":
            return "SpaceX"
        if constellation == "OneWeb":
            return "Eutelsat OneWeb"
        if constellation == "Iridium":
            return "Iridium"
        return "Unknown"

    def _get_cached_tle(self, ignore_ttl: bool) -> str | None:
        try:
            if not ignore_ttl:
                ttl = self.redis_client.ttl(self.cache_key)
                if ttl <= 0:
                    return None
            raw = self.redis_client.get(self.cache_key)
        except Exception:
            return None

        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")

        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except Exception:
                self._tle_source = "cache"
                return raw
            if isinstance(payload, dict) and isinstance(payload.get("tle"), str):
                self._tle_source = str(payload.get("source") or "cache")
                fetched_at = payload.get("fetched_at")
                if isinstance(fetched_at, str):
                    try:
                        self._last_update = ensure_utc(datetime.fromisoformat(fetched_at.replace("Z", "+00:00")))
                    except ValueError:
                        self._last_update = None
                return payload["tle"]
        return None

    def _cache_tle_data(self, payload: str) -> None:
        cache_payload = {
            "tle": payload,
            "source": self._tle_source,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.redis_client.setex(self.cache_key, self.cache_ttl, json.dumps(cache_payload))
            self._last_update = datetime.now(timezone.utc)
        except Exception:
            return

    def _refresh_celestrak_tles(self) -> str:
        response = requests.get(self.tle_url, timeout=30)
        response.raise_for_status()
        payload = response.text
        if not payload.strip():
            raise ValueError("CelesTrak returned an empty TLE payload")
        return payload

    def _refresh_space_track_tles(self, current_tle_data: str | None = None) -> str:
        if not self.space_track_identity or not self.space_track_password:
            raise ValueError("Space-Track credentials are not configured")

        query_url = (
            SPACE_TRACK_STARLINK_GP_DELTA_URL
            if current_tle_data and current_tle_data.strip()
            else SPACE_TRACK_STARLINK_GP_FULL_URL
        )

        with requests.Session() as session:
            self._enforce_space_track_rate_limits()
            login_response = session.post(
                SPACE_TRACK_LOGIN_URL,
                data={
                    "identity": self.space_track_identity,
                    "password": self.space_track_password,
                },
                timeout=self.space_track_timeout_seconds,
            )
            self._register_space_track_request()
            login_response.raise_for_status()
            if (login_response.text or "").strip() not in {"", '""'}:
                raise ConnectionError("Space-Track login failed")

            self._enforce_space_track_rate_limits()
            data_response = session.get(query_url, timeout=self.space_track_timeout_seconds)
            self._register_space_track_request()
            data_response.raise_for_status()
            payload = data_response.text

        if current_tle_data and current_tle_data.strip():
            return self._merge_tle_sets(current_tle_data, payload)
        if not payload.strip():
            raise ValueError("Space-Track returned an empty TLE payload")
        return payload

    def _iter_tle_triplets(self, payload: str) -> list[tuple[str, str, str]]:
        lines = [line.strip() for line in payload.splitlines() if line.strip()]
        triplets: list[tuple[str, str, str]] = []
        index = 0
        while index < len(lines):
            if (
                lines[index].startswith("1 ")
                and index + 1 < len(lines)
                and lines[index + 1].startswith("2 ")
            ):
                sat_id = lines[index][2:7].strip() or "UNKNOWN"
                triplets.append((f"SATELLITE {sat_id}", lines[index], lines[index + 1]))
                index += 2
                continue
            if (
                index + 2 < len(lines)
                and lines[index + 1].startswith("1 ")
                and lines[index + 2].startswith("2 ")
            ):
                triplets.append((lines[index], lines[index + 1], lines[index + 2]))
                index += 3
                continue
            index += 1
        return triplets

    def _merge_tle_sets(self, base_payload: str, delta_payload: str) -> str:
        if not delta_payload.strip():
            return base_payload
        merged: dict[str, tuple[str, str, str]] = {}
        order: list[str] = []

        for name, line1, line2 in self._iter_tle_triplets(base_payload):
            sat_id = line1[2:7].strip() or name
            if sat_id not in merged:
                order.append(sat_id)
            merged[sat_id] = (name, line1, line2)

        for name, line1, line2 in self._iter_tle_triplets(delta_payload):
            sat_id = line1[2:7].strip() or name
            if sat_id not in merged:
                order.append(sat_id)
            merged[sat_id] = (name, line1, line2)

        lines: list[str] = []
        for sat_id in order:
            name, line1, line2 = merged[sat_id]
            lines.extend([name, line1, line2])
        return "\n".join(lines) + ("\n" if lines else "")

    def _load_space_track_gate_from_cache(self) -> None:
        if self._space_track_next_fetch_ts > 0:
            return
        try:
            raw = self.redis_client.get(self._space_track_gate_cache_key)
        except Exception:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        if value > 0.0:
            self._space_track_next_fetch_ts = value

    def _persist_space_track_gate(self, next_fetch_ts: float) -> None:
        self._space_track_next_fetch_ts = float(next_fetch_ts)
        try:
            self.redis_client.setex(self._space_track_gate_cache_key, 86400 * 7, str(next_fetch_ts))
        except Exception:
            return

    def _schedule_next_space_track_fetch_ts(self) -> float:
        due_ts = time.time() + self.space_track_min_interval_seconds
        due_dt = datetime.fromtimestamp(due_ts, tz=timezone.utc)
        if due_dt.minute < 5 or due_dt.minute > 55:
            due_dt = due_dt + timedelta(minutes=random.randint(7, 17))
        return due_dt.timestamp()

    def _space_track_fetch_allowed(self, force_refresh: bool) -> bool:
        if force_refresh:
            return True
        self._load_space_track_gate_from_cache()
        return time.time() >= self._space_track_next_fetch_ts

    def _prune_space_track_rate_window(self, now_ts: float) -> None:
        while self._space_track_query_timestamps and (now_ts - self._space_track_query_timestamps[0] > 3600.0):
            self._space_track_query_timestamps.popleft()

    def _enforce_space_track_rate_limits(self) -> None:
        now_ts = time.time()
        self._prune_space_track_rate_window(now_ts)
        hour_count = len(self._space_track_query_timestamps)
        minute_count = sum(1 for ts in self._space_track_query_timestamps if now_ts - ts <= 60.0)
        if hour_count >= self.space_track_per_hour_limit:
            raise RuntimeError("Space-Track hourly request limit reached")
        if minute_count >= self.space_track_per_minute_limit:
            raise RuntimeError("Space-Track minute request limit reached")

    def _register_space_track_request(self) -> None:
        now_ts = time.time()
        self._prune_space_track_rate_window(now_ts)
        self._space_track_query_timestamps.append(now_ts)
