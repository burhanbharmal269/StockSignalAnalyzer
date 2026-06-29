"""API rate limiting middleware — per-IP sliding window using Redis.

Applies to ALL API routes (not just login). Configurable via:
  RATE_LIMIT_REQUESTS_PER_MINUTE  (default: 120)
  RATE_LIMIT_BURST                (default: 30)

Algorithm: sliding window counter in Redis.
Key: rate:api:{ip_hash}   TTL = 60s
On limit exceeded: 429 Too Many Requests with Retry-After header.

Admin routes (/api/v1/broker/kill-switch) get a tighter limit (20/min).
Health and metrics endpoints are exempt.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_log = logging.getLogger(__name__)

_EXEMPT_PREFIXES = ("/api/v1/health", "/metrics", "/docs", "/openapi", "/redoc")
_SENSITIVE_PREFIXES = ("/api/v1/broker/kill-switch", "/api/v1/audit", "/api/v1/reconciliation/trigger")

_WINDOW_SECONDS = 60
_DEFAULT_LIMIT = 600   # raised 120→600: single-user app polls 5+ endpoints per cycle;
                       # 120/min was hit in <60s with normal UI polling load
_SENSITIVE_LIMIT = 20


class ApiRateLimiterMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-IP rate limiter applied to all non-exempt routes."""

    def __init__(
        self,
        app,
        redis_client,
        requests_per_minute: int = _DEFAULT_LIMIT,
        enabled: bool = True,
    ) -> None:
        super().__init__(app)
        self._redis = redis_client
        self._limit = requests_per_minute
        self._enabled = enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        ip = self._client_ip(request)
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
        limit = _SENSITIVE_LIMIT if any(path.startswith(p) for p in _SENSITIVE_PREFIXES) else self._limit

        try:
            key = f"rate:api:{ip_hash}"
            now = int(time.time())
            window_start = now - _WINDOW_SECONDS

            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now * 1000 + id(request)): now})
            pipe.zcard(key)
            pipe.expire(key, _WINDOW_SECONDS + 5)
            results = await pipe.execute()
            count = results[2]
        except Exception:
            # Redis unavailable — fail open (let request through)
            _log.warning("api_rate_limiter.redis_error — failing open")
            return await call_next(request)

        if count > limit:
            _log.warning("api_rate_limit_exceeded ip_hash=%s path=%s count=%d", ip_hash, path, count)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retry_after_seconds": _WINDOW_SECONDS,
                },
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "0.0.0.0"  # noqa: S104
