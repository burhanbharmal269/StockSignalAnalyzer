"""LoginRateLimiter — Redis-backed brute-force protection for login endpoints.

Redis key schema (Doc 23 §4.3):
  auth:attempts:{ip_hash}   →  failure count  (TTL = attempt_window_seconds)
  auth:lockout:{ip_hash}    →  "1"            (TTL = lockout_seconds)

The IP address is SHA-256 hashed (first 16 hex chars) before use as a key
suffix to reduce information exposure in Redis key names.

Behaviour:
  - is_locked_out(ip)     → True if lockout key exists
  - record_failure(ip)    → increments counter; sets lockout if threshold reached
  - record_success(ip)    → clears both counter and lockout keys
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis


class LoginRateLimiter:
    _ATTEMPT_PREFIX = "auth:attempts:"
    _LOCKOUT_PREFIX = "auth:lockout:"

    def __init__(
        self,
        redis_client: Redis,  # type: ignore[type-arg]
        max_attempts: int = 5,
        attempt_window_seconds: int = 600,
        lockout_seconds: int = 1800,
    ) -> None:
        self._redis = redis_client
        self._max_attempts = max_attempts
        self._window = attempt_window_seconds
        self._lockout = lockout_seconds

    def _hashed_ip(self, ip: str) -> str:
        return hashlib.sha256(ip.encode()).hexdigest()[:16]

    async def is_locked_out(self, ip: str) -> bool:
        """Return True if this IP is currently in the lockout window."""
        key = self._LOCKOUT_PREFIX + self._hashed_ip(ip)
        return bool(await self._redis.exists(key))

    async def record_failure(self, ip: str) -> int:
        """Increment failure counter; apply lockout when threshold is reached.

        Returns the current failure count after incrementing.
        """
        hashed = self._hashed_ip(ip)
        attempt_key = self._ATTEMPT_PREFIX + hashed
        lockout_key = self._LOCKOUT_PREFIX + hashed

        count = await self._redis.incr(attempt_key)
        if count == 1:
            # Set TTL only on first increment so the window slides from first failure.
            await self._redis.expire(attempt_key, self._window)

        if count >= self._max_attempts:
            await self._redis.setex(lockout_key, self._lockout, "1")

        return int(count)

    async def record_success(self, ip: str) -> None:
        """Clear failure state on a successful login."""
        hashed = self._hashed_ip(ip)
        await self._redis.delete(
            self._ATTEMPT_PREFIX + hashed,
            self._LOCKOUT_PREFIX + hashed,
        )
