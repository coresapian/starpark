# -*- coding: utf-8 -*-
# Copyright (c) 2024, LinkSpot Project Contributors
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
LinkSpot Redis Cache Client

High-performance Redis client for hot caching with geohash-based keys.
Supports JSON serialization, TTL management, and specialized methods
for building, TLE, and analysis result caching.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import timedelta

import redis.asyncio as aioredis
import redis
import pygeohash as pgh

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis cache client for LinkSpot hot caching layer.
    
    Provides geohash-based caching for building data, TLE data, and
    analysis results with configurable TTL values.
    
    Key formats:
        - Buildings: "buildings:{geohash}"
        - TLEs: "tles:{constellation}"
        - Analysis: "analysis:{geohash}"
    
    Example:
        >>> cache = RedisCache("redis://localhost:6379")
        >>> await cache.connect()
        >>> 
        >>> # Cache buildings
        >>> await cache.set_buildings("dqcjqc", buildings_data)
        >>> 
        >>> # Retrieve buildings
        >>> buildings = await cache.get_buildings("dqcjqc")
        >>> 
        >>> await cache.close()
    
    Attributes:
        redis_url: Redis connection URL
        redis: Redis client instance (sync)
        redis_async: Redis client instance (async)
        default_ttl: Default TTL in seconds
    """
    
    # Default TTL values (in seconds)
    DEFAULT_BUILDING_TTL = 86400  # 24 hours
    DEFAULT_TLE_TTL = 14400       # 4 hours
    DEFAULT_ANALYSIS_TTL = 86400  # 24 hours
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 3600,
        decode_responses: bool = True,
    ):
        """
        Initialize Redis cache client.
        
        Args:
            redis_url: Redis connection URL
            default_ttl: Default TTL in seconds
            decode_responses: Automatically decode responses to strings
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.decode_responses = decode_responses
        
        self._redis: Optional[redis.Redis] = None
        self._redis_async: Optional[aioredis.Redis] = None
        
        logger.info(f"RedisCache initialized with URL: {redis_url}")
    
    def connect(self) -> None:
        """
        Establish synchronous Redis connection.
        
        Creates a connection pool for sync operations.
        """
        self._redis = redis.from_url(
            self.redis_url,
            decode_responses=self.decode_responses,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        logger.info("Redis sync connection established")
    
    async def connect_async(self) -> None:
        """
        Establish asynchronous Redis connection.
        
        Creates a connection pool for async operations.
        """
        self._redis_async = aioredis.from_url(
            self.redis_url,
            decode_responses=self.decode_responses,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        logger.info("Redis async connection established")
    
    def close(self) -> None:
        """Close synchronous Redis connection."""
        if self._redis:
            self._redis.close()
            self._redis = None
            logger.info("Redis sync connection closed")
    
    async def close_async(self) -> None:
        """Close asynchronous Redis connection."""
        if self._redis_async:
            await self._redis_async.close()
            self._redis_async = None
            logger.info("Redis async connection closed")
    
    # =========================================================================
    # Basic Operations
    # =========================================================================
    
    def get(self, key: str) -> Optional[str]:
        """
        Get string value by key.
        
        Args:
            key: Redis key
            
        Returns:
            String value or None if not found
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        value = self._redis.get(key)
        return value if value is not None else None
    
    async def get_async(self, key: str) -> Optional[str]:
        """Async version of get."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        value = await self._redis_async.get(key)
        return value if value is not None else None
    
    def set(
        self,
        key: str,
        value: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set string value with optional TTL.
        
        Args:
            key: Redis key
            value: String value
            ttl_seconds: TTL in seconds (None for no expiration)
            
        Returns:
            True if successful
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        
        if ttl > 0:
            return self._redis.setex(key, ttl, value)
        else:
            return self._redis.set(key, value)
    
    async def set_async(
        self,
        key: str,
        value: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Async version of set."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        
        if ttl > 0:
            return await self._redis_async.setex(key, ttl, value)
        else:
            return await self._redis_async.set(key, value)
    
    def get_json(self, key: str) -> Optional[Any]:
        """
        Get and deserialize JSON value.
        
        Args:
            key: Redis key
            
        Returns:
            Deserialized JSON value or None
        """
        value = self.get(key)
        if value is not None:
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON for key {key}: {e}")
                return None
        return None
    
    async def get_json_async(self, key: str) -> Optional[Any]:
        """Async version of get_json."""
        value = await self.get_async(key)
        if value is not None:
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON for key {key}: {e}")
                return None
        return None
    
    def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Serialize and set JSON value.
        
        Args:
            key: Redis key
            value: JSON-serializable value
            ttl_seconds: TTL in seconds
            
        Returns:
            True if successful
        """
        try:
            json_value = json.dumps(value, default=str)
            return self.set(key, json_value, ttl_seconds)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to encode JSON for key {key}: {e}")
            return False
    
    async def set_json_async(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Async version of set_json."""
        try:
            json_value = json.dumps(value, default=str)
            return await self.set_async(key, json_value, ttl_seconds)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to encode JSON for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> int:
        """
        Delete key from Redis.
        
        Args:
            key: Redis key to delete
            
        Returns:
            Number of keys deleted
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        return self._redis.delete(key)
    
    async def delete_async(self, key: str) -> int:
        """Async version of delete."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        return await self._redis_async.delete(key)
    
    def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching pattern.
        
        WARNING: Use with caution on large keyspaces.
        
        Args:
            pattern: Key pattern (e.g., "buildings:*")
            
        Returns:
            Number of keys deleted
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        keys = self._redis.keys(pattern)
        if keys:
            return self._redis.delete(*keys)
        return 0
    
    async def delete_pattern_async(self, pattern: str) -> int:
        """Async version of delete_pattern."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        keys = []
        async for key in self._redis_async.scan_iter(match=pattern):
            keys.append(key)
        
        if keys:
            return await self._redis_async.delete(*keys)
        return 0
    
    def exists(self, key: str) -> bool:
        """
        Check if key exists.
        
        Args:
            key: Redis key
            
        Returns:
            True if key exists
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        return self._redis.exists(key) > 0
    
    async def exists_async(self, key: str) -> bool:
        """Async version of exists."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        return await self._redis_async.exists(key) > 0
    
    def ttl(self, key: str) -> int:
        """
        Get remaining TTL for key.
        
        Args:
            key: Redis key
            
        Returns:
            TTL in seconds, -1 if no TTL, -2 if key doesn't exist
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        return self._redis.ttl(key)
    
    async def ttl_async(self, key: str) -> int:
        """Async version of ttl."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        return await self._redis_async.ttl(key)
    
    # =========================================================================
    # Building Cache Operations
    # =========================================================================
    
    def _buildings_key(self, geohash: str) -> str:
        """Generate Redis key for buildings cache."""
        return f"buildings:{geohash}"
    
    def get_buildings(self, geohash: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached buildings for a geohash.
        
        Args:
            geohash: Geohash string (typically precision 6)
            
        Returns:
            List of building dictionaries or None
        """
        key = self._buildings_key(geohash)
        return self.get_json(key)
    
    async def get_buildings_async(self, geohash: str) -> Optional[List[Dict[str, Any]]]:
        """Async version of get_buildings."""
        key = self._buildings_key(geohash)
        return await self.get_json_async(key)
    
    def set_buildings(
        self,
        geohash: str,
        buildings_data: List[Dict[str, Any]],
        ttl: int = DEFAULT_BUILDING_TTL,
    ) -> bool:
        """
        Cache buildings for a geohash.
        
        Args:
            geohash: Geohash string
            buildings_data: List of building dictionaries
            ttl: TTL in seconds (default: 24 hours)
            
        Returns:
            True if successful
        """
        key = self._buildings_key(geohash)
        cache_entry = {
            "geohash": geohash,
            "buildings": buildings_data,
            "count": len(buildings_data),
            "cached_at": json.dumps(None, default=str),  # Will be set by set_json
        }
        return self.set_json(key, cache_entry, ttl)
    
    async def set_buildings_async(
        self,
        geohash: str,
        buildings_data: List[Dict[str, Any]],
        ttl: int = DEFAULT_BUILDING_TTL,
    ) -> bool:
        """Async version of set_buildings."""
        key = self._buildings_key(geohash)
        from datetime import datetime
        cache_entry = {
            "geohash": geohash,
            "buildings": buildings_data,
            "count": len(buildings_data),
            "cached_at": datetime.utcnow().isoformat(),
        }
        return await self.set_json_async(key, cache_entry, ttl)
    
    def invalidate_buildings(self, geohash: str) -> int:
        """
        Invalidate cached buildings for a geohash.
        
        Args:
            geohash: Geohash string
            
        Returns:
            Number of keys deleted
        """
        key = self._buildings_key(geohash)
        return self.delete(key)
    
    async def invalidate_buildings_async(self, geohash: str) -> int:
        """Async version of invalidate_buildings."""
        key = self._buildings_key(geohash)
        return await self.delete_async(key)
    
    def invalidate_buildings_pattern(self, pattern: str = "buildings:*") -> int:
        """
        Invalidate all cached buildings matching pattern.
        
        Args:
            pattern: Key pattern (default: "buildings:*")
            
        Returns:
            Number of keys deleted
        """
        return self.delete_pattern(pattern)
    
    async def invalidate_buildings_pattern_async(self, pattern: str = "buildings:*") -> int:
        """Async version of invalidate_buildings_pattern."""
        return await self.delete_pattern_async(pattern)
    
    # =========================================================================
    # TLE Cache Operations
    # =========================================================================
    
    def _tles_key(self, constellation: str) -> str:
        """Generate Redis key for TLE cache."""
        return f"tles:{constellation.lower()}"
    
    def get_tles(self, constellation: str) -> Optional[str]:
        """
        Get cached TLE data for a constellation.
        
        Args:
            constellation: Constellation name (e.g., 'starlink')
            
        Returns:
            Raw TLE text or None
        """
        key = self._tles_key(constellation)
        return self.get(key)
    
    async def get_tles_async(self, constellation: str) -> Optional[str]:
        """Async version of get_tles."""
        key = self._tles_key(constellation)
        return await self.get_async(key)
    
    def set_tles(
        self,
        constellation: str,
        tle_data: str,
        ttl: int = DEFAULT_TLE_TTL,
    ) -> bool:
        """
        Cache TLE data for a constellation.
        
        Args:
            constellation: Constellation name
            tle_data: Raw TLE text
            ttl: TTL in seconds (default: 4 hours)
            
        Returns:
            True if successful
        """
        key = self._tles_key(constellation)
        return self.set(key, tle_data, ttl)
    
    async def set_tles_async(
        self,
        constellation: str,
        tle_data: str,
        ttl: int = DEFAULT_TLE_TTL,
    ) -> bool:
        """Async version of set_tles."""
        key = self._tles_key(constellation)
        return await self.set_async(key, tle_data, ttl)
    
    def invalidate_tles(self, constellation: str) -> int:
        """
        Invalidate cached TLEs for a constellation.
        
        Args:
            constellation: Constellation name
            
        Returns:
            Number of keys deleted
        """
        key = self._tles_key(constellation)
        return self.delete(key)
    
    async def invalidate_tles_async(self, constellation: str) -> int:
        """Async version of invalidate_tles."""
        key = self._tles_key(constellation)
        return await self.delete_async(key)
    
    # =========================================================================
    # Analysis Cache Operations
    # =========================================================================
    
    def _analysis_key(self, geohash: str) -> str:
        """Generate Redis key for analysis cache."""
        return f"analysis:{geohash}"
    
    def get_analysis(self, geohash: str) -> Optional[Dict[str, Any]]:
        """
        Get cached analysis result for a geohash.
        
        Args:
            geohash: Geohash string
            
        Returns:
            Analysis result dictionary or None
        """
        key = self._analysis_key(geohash)
        return self.get_json(key)
    
    async def get_analysis_async(self, geohash: str) -> Optional[Dict[str, Any]]:
        """Async version of get_analysis."""
        key = self._analysis_key(geohash)
        return await self.get_json_async(key)
    
    def set_analysis(
        self,
        geohash: str,
        result: Dict[str, Any],
        ttl: int = DEFAULT_ANALYSIS_TTL,
    ) -> bool:
        """
        Cache analysis result for a geohash.
        
        Args:
            geohash: Geohash string
            result: Analysis result dictionary
            ttl: TTL in seconds (default: 24 hours)
            
        Returns:
            True if successful
        """
        key = self._analysis_key(geohash)
        from datetime import datetime
        cache_entry = {
            "geohash": geohash,
            "result": result,
            "cached_at": datetime.utcnow().isoformat(),
        }
        return self.set_json(key, cache_entry, ttl)
    
    async def set_analysis_async(
        self,
        geohash: str,
        result: Dict[str, Any],
        ttl: int = DEFAULT_ANALYSIS_TTL,
    ) -> bool:
        """Async version of set_analysis."""
        key = self._analysis_key(geohash)
        from datetime import datetime
        cache_entry = {
            "geohash": geohash,
            "result": result,
            "cached_at": datetime.utcnow().isoformat(),
        }
        return await self.set_json_async(key, cache_entry, ttl)
    
    # =========================================================================
    # Geohash Utilities
    # =========================================================================
    
    @staticmethod
    def compute_geohash(lat: float, lon: float, precision: int = 6) -> str:
        """
        Compute geohash for coordinates.
        
        Args:
            lat: Latitude
            lon: Longitude
            precision: Geohash precision (default: 6)
            
        Returns:
            Geohash string
        """
        return pgh.encode(lat, lon, precision=precision)
    
    @staticmethod
    def geohash_to_bbox(geohash: str) -> tuple:
        """
        Convert geohash to bounding box.
        
        Args:
            geohash: Geohash string
            
        Returns:
            Tuple of (lat, lon, lat_err, lon_err)
        """
        return pgh.decode_exactly(geohash)
    
    @staticmethod
    def get_neighbor_geohashes(geohash: str) -> Dict[str, str]:
        """
        Get all 8 neighboring geohashes.
        
        Args:
            geohash: Center geohash
            
        Returns:
            Dictionary with neighbor geohashes
        """
        return pgh.neighbors(geohash)
    
    # =========================================================================
    # Health and Stats
    # =========================================================================
    
    def health_check(self) -> bool:
        """
        Check Redis connectivity.
        
        Returns:
            True if Redis is accessible
        """
        if self._redis is None:
            return False
        
        try:
            return self._redis.ping()
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    async def health_check_async(self) -> bool:
        """Async version of health_check."""
        if self._redis_async is None:
            return False
        
        try:
            return await self._redis_async.ping()
        except Exception as e:
            logger.error(f"Redis health check failed (async): {e}")
            return False
    
    def info(self) -> Dict[str, Any]:
        """
        Get Redis server info.
        
        Returns:
            Dictionary with Redis info
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        return self._redis.info()
    
    async def info_async(self) -> Dict[str, Any]:
        """Async version of info."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        return await self._redis_async.info()
    
    def dbsize(self) -> int:
        """
        Get number of keys in database.
        
        Returns:
            Number of keys
        """
        if self._redis is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        return self._redis.dbsize()
    
    async def dbsize_async(self) -> int:
        """Async version of dbsize."""
        if self._redis_async is None:
            raise RuntimeError("Redis not connected. Call connect_async() first.")
        
        return await self._redis_async.dbsize()


# Convenience function for quick cache setup
async def create_redis_cache(
    redis_url: str = "redis://localhost:6379",
    connect: bool = True,
) -> RedisCache:
    """
    Create and optionally connect Redis cache.
    
    Args:
        redis_url: Redis connection URL
        connect: Connect immediately
        
    Returns:
        Configured RedisCache instance
    """
    cache = RedisCache(redis_url)
    if connect:
        await cache.connect_async()
    return cache


__all__ = [
    "RedisCache",
    "create_redis_cache",
]
