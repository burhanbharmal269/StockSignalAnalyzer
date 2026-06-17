"""RedisSignalCacheRepository — Redis implementation of ISignalCacheRepository."""

from __future__ import annotations

import logging

from core.domain.interfaces.i_signal_cache_repository import ISignalCacheRepository

_log = logging.getLogger(__name__)


class RedisSignalCacheRepository(ISignalCacheRepository):
    """Stores signal dedup keys and active signal metadata in Redis."""

    def __init__(self, redis: object) -> None:
        self._redis = redis

    async def is_duplicate(self, dedup_key: str) -> bool:
        try:
            value = await self._redis.get(dedup_key)
            return value is not None
        except Exception:
            _log.warning("Redis error checking dedup key %r — treating as non-duplicate", dedup_key)
            return False

    async def set_dedup(
        self, dedup_key: str, signal_id: str, ttl_seconds: int
    ) -> None:
        try:
            await self._redis.set(dedup_key, signal_id, ex=ttl_seconds)
        except Exception:
            _log.warning("Redis error setting dedup key %r for signal %s", dedup_key, signal_id)

    async def get_active_signal_id(self, instrument_token: int) -> str | None:
        key = f"signal:active:{instrument_token}"
        try:
            value = await self._redis.get(key)
            return value.decode() if isinstance(value, bytes) else value
        except Exception:
            _log.warning("Redis error getting active signal for token %s", instrument_token)
            return None

    async def set_active_signal(
        self, instrument_token: int, signal_id: str, ttl_seconds: int
    ) -> None:
        key = f"signal:active:{instrument_token}"
        try:
            await self._redis.set(key, signal_id, ex=ttl_seconds)
        except Exception:
            _log.warning("Redis error setting active signal for token %s", instrument_token)

    async def delete_active_signal(self, instrument_token: int) -> None:
        key = f"signal:active:{instrument_token}"
        try:
            await self._redis.delete(key)
        except Exception:
            _log.warning("Redis error deleting active signal for token %s", instrument_token)
