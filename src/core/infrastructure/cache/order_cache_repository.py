"""Redis implementation of IOrderCacheRepository.

All methods are fail-open: Redis errors are logged as WARNING.
Redis is a performance cache; the DB is the source of truth.

Exception: set_idempotency_key() — Redis failure falls back to False
(non-duplicate), which means a retry will attempt to create a duplicate order.
Callers must guard against this via DB unique constraints.
"""

from __future__ import annotations

import logging
from uuid import UUID

import redis.asyncio as aioredis

from core.domain.interfaces.i_order_cache_repository import IOrderCacheRepository
from core.infrastructure.config.oms_config import OmsConfig

_log = logging.getLogger(__name__)


class RedisOrderCacheRepository(IOrderCacheRepository):
    def __init__(self, redis: aioredis.Redis, config: OmsConfig) -> None:
        self._redis = redis
        self._config = config

    async def set_idempotency_key(
        self,
        signal_id: UUID,
        order_id: UUID,
        ttl_seconds: int = 300,
    ) -> bool:
        """SET NX oms:idem:{signal_id} → order_id with TTL.

        Returns True if key was newly set (first occurrence).
        Returns False if key already exists (duplicate — discard signal).
        Falls back to True (non-duplicate) on Redis failure.
        """
        key = self._config.idempotency_key(str(signal_id))
        try:
            result = await self._redis.set(
                key,
                str(order_id),
                nx=True,
                ex=ttl_seconds,
            )
            return result is not None  # None means key existed already
        except Exception:
            _log.warning(
                "Redis error setting idempotency key for signal_id=%s — fail-open",
                signal_id,
            )
            return True  # fail-open: assume first occurrence

    async def get_idempotency_order_id(self, signal_id: UUID) -> UUID | None:
        key = self._config.idempotency_key(str(signal_id))
        try:
            value = await self._redis.get(key)
            if value is None:
                return None
            raw = value.decode() if isinstance(value, bytes) else value
            return UUID(raw)
        except Exception:
            _log.warning(
                "Redis error reading idempotency key for signal_id=%s", signal_id
            )
            return None

    async def cache_order(
        self,
        order_id: UUID,
        order_json: str,
        ttl_seconds: int = 900,
    ) -> None:
        key = self._config.order_cache_key(str(order_id))
        try:
            await self._redis.set(key, order_json, ex=ttl_seconds)
        except Exception:
            _log.warning("Redis error caching order %s", order_id)

    async def get_cached_order(self, order_id: UUID) -> str | None:
        key = self._config.order_cache_key(str(order_id))
        try:
            value = await self._redis.get(key)
            if value is None:
                return None
            return value.decode() if isinstance(value, bytes) else value
        except Exception:
            _log.warning("Redis error reading cached order %s", order_id)
            return None

    async def evict_order(self, order_id: UUID) -> None:
        key = self._config.order_cache_key(str(order_id))
        try:
            await self._redis.delete(key)
        except Exception:
            _log.warning("Redis error evicting order %s from cache", order_id)

    async def cache_position(
        self,
        position_id: UUID,
        position_json: str,
        ttl_seconds: int = 86400,
    ) -> None:
        key = self._config.position_cache_key(str(position_id))
        try:
            await self._redis.set(key, position_json, ex=ttl_seconds)
        except Exception:
            _log.warning("Redis error caching position %s", position_id)

    async def get_cached_position(self, position_id: UUID) -> str | None:
        key = self._config.position_cache_key(str(position_id))
        try:
            value = await self._redis.get(key)
            if value is None:
                return None
            return value.decode() if isinstance(value, bytes) else value
        except Exception:
            _log.warning("Redis error reading cached position %s", position_id)
            return None

    async def evict_position(self, position_id: UUID) -> None:
        key = self._config.position_cache_key(str(position_id))
        try:
            await self._redis.delete(key)
        except Exception:
            _log.warning("Redis error evicting position %s from cache", position_id)
