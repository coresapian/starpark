# Copyright (c) 2024, LinkSpot Team
# BSD 3-Clause License
#
# Rate limiting middleware for API protection.
# Uses sliding window algorithm with Redis backend.

"""Rate limiting middleware for LinkSpot API."""

import logging
import time
from typing import Optional

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from config import settings

# Configure logging
logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using sliding window algorithm.
    
    Limits requests per client IP address within a time window.
    Uses in-memory storage for rate limit tracking.
    
    For production, consider using Redis for distributed rate limiting.
    
    Attributes:
        app: The ASGI application.
        max_requests: Maximum requests allowed per window.
        window_seconds: Time window in seconds.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        """Initialize rate limiting middleware.
        
        Args:
            app: The ASGI application.
            max_requests: Maximum requests allowed per window.
            window_seconds: Time window in seconds.
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
        # In-memory rate limit storage
        # For production, use Redis: key -> list of timestamps
        self._request_log: dict[str, list[float]] = {}
        
        logger.info(
            f"Rate limiting enabled: {max_requests} requests per {window_seconds}s"
        )
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request.
        
        Uses X-Forwarded-For header if present, otherwise uses client IP.
        
        Args:
            request: FastAPI request object.
            
        Returns:
            str: Client identifier.
        """
        # Check for forwarded IP (behind proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Use first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        # Use direct client IP
        if request.client:
            return request.client.host
        
        # Fallback
        return "unknown"
    
    def _is_rate_limited(self, client_id: str) -> tuple[bool, dict]:
        """Check if client has exceeded rate limit.
        
        Args:
            client_id: Client identifier.
            
        Returns:
            tuple: (is_limited, rate_limit_info)
        """
        now = time.time()
        window_start = now - self.window_seconds
        
        # Get client's request history
        if client_id not in self._request_log:
            self._request_log[client_id] = []
        
        request_history = self._request_log[client_id]
        
        # Remove old requests outside the window
        request_history[:] = [t for t in request_history if t > window_start]
        
        # Count requests in current window
        request_count = len(request_history)
        
        # Calculate rate limit info
        remaining = max(0, self.max_requests - request_count)
        reset_time = int(window_start + self.window_seconds)
        
        rate_limit_info = {
            "limit": self.max_requests,
            "remaining": remaining,
            "reset": reset_time,
            "window": self.window_seconds,
        }
        
        # Check if rate limited
        if request_count >= self.max_requests:
            return True, rate_limit_info
        
        # Record this request
        request_history.append(now)
        
        return False, rate_limit_info
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with rate limiting.
        
        Args:
            request: FastAPI request object.
            call_next: Next middleware/handler in chain.
            
        Returns:
            Response: The response from the next handler.
        """
        # Skip rate limiting for health checks
        if request.url.path in ["/api/v1/health", "/health", "/ready", "/live"]:
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_id(request)
        
        # Check rate limit
        is_limited, rate_limit_info = self._is_rate_limited(client_id)
        
        if is_limited:
            logger.warning(
                f"Rate limit exceeded for client {client_id}: "
                f"{rate_limit_info['limit']} requests per {self.window_seconds}s"
            )
            
            # Return 429 Too Many Requests
            from fastapi.responses import JSONResponse
            
            retry_after = int(self.window_seconds)
            
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "type": "https://api.linkspot.io/errors/rate-limit-exceeded",
                    "title": "Rate Limit Exceeded",
                    "status": 429,
                    "detail": (
                        f"Rate limit exceeded. "
                        f"Maximum {self.max_requests} requests per {self.window_seconds} seconds."
                    ),
                    "instance": str(request.url.path),
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rate_limit_info["limit"]),
                    "X-RateLimit-Remaining": str(rate_limit_info["remaining"]),
                    "X-RateLimit-Reset": str(rate_limit_info["reset"]),
                    "X-RateLimit-Window": str(rate_limit_info["window"]),
                },
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(rate_limit_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_limit_info["reset"])
        response.headers["X-RateLimit-Window"] = str(rate_limit_info["window"])
        
        return response


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis for distributed rate limiting.
    
    This is an alternative implementation that uses Redis for storing
    rate limit counters, suitable for multi-instance deployments.
    
    Note: This requires Redis to be available and configured.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        max_requests: int = 100,
        window_seconds: int = 60,
        redis_url: Optional[str] = None,
    ) -> None:
        """Initialize Redis-based rate limiting middleware.
        
        Args:
            app: The ASGI application.
            max_requests: Maximum requests allowed per window.
            window_seconds: Time window in seconds.
            redis_url: Redis connection URL.
        """
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_url = redis_url or str(settings.redis_url)
        self._redis = None
        
        logger.info(
            f"Redis rate limiting enabled: {max_requests} requests per {window_seconds}s"
        )
    
    async def _get_redis(self):
        """Get or create Redis connection."""
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        if request.client:
            return request.client.host
        
        return "unknown"
    
    async def _is_rate_limited(self, client_id: str) -> tuple[bool, dict]:
        """Check if client has exceeded rate limit using Redis.
        
        Uses Redis sorted sets for sliding window rate limiting.
        """
        redis = await self._get_redis()
        key = f"ratelimit:{client_id}"
        now = time.time()
        window_start = now - self.window_seconds
        
        # Remove old entries
        await redis.zremrangebyscore(key, 0, window_start)
        
        # Count current requests
        request_count = await redis.zcard(key)
        
        # Calculate rate limit info
        remaining = max(0, self.max_requests - request_count)
        reset_time = int(window_start + self.window_seconds)
        
        rate_limit_info = {
            "limit": self.max_requests,
            "remaining": remaining,
            "reset": reset_time,
            "window": self.window_seconds,
        }
        
        # Check if rate limited
        if request_count >= self.max_requests:
            return True, rate_limit_info
        
        # Add current request
        await redis.zadd(key, {str(now): now})
        await redis.expire(key, self.window_seconds)
        
        return False, rate_limit_info
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with Redis-based rate limiting."""
        # Skip rate limiting for health checks
        if request.url.path in ["/api/v1/health", "/health", "/ready", "/live"]:
            return await call_next(request)
        
        client_id = self._get_client_id(request)
        
        try:
            is_limited, rate_limit_info = await self._is_rate_limited(client_id)
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Allow request if rate limit check fails
            return await call_next(request)
        
        if is_limited:
            logger.warning(f"Rate limit exceeded for client {client_id}")
            
            from fastapi.responses import JSONResponse
            
            retry_after = int(self.window_seconds)
            
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "type": "https://api.linkspot.io/errors/rate-limit-exceeded",
                    "title": "Rate Limit Exceeded",
                    "status": 429,
                    "detail": (
                        f"Rate limit exceeded. "
                        f"Maximum {self.max_requests} requests per {self.window_seconds} seconds."
                    ),
                    "instance": str(request.url.path),
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rate_limit_info["limit"]),
                    "X-RateLimit-Remaining": str(rate_limit_info["remaining"]),
                    "X-RateLimit-Reset": str(rate_limit_info["reset"]),
                    "X-RateLimit-Window": str(rate_limit_info["window"]),
                },
            )
        
        response = await call_next(request)
        
        response.headers["X-RateLimit-Limit"] = str(rate_limit_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_limit_info["reset"])
        response.headers["X-RateLimit-Window"] = str(rate_limit_info["window"])
        
        return response
