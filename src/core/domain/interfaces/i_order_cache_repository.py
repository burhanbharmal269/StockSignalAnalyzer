"""IOrderCacheRepository — Redis port for live order and position caching.

Redis is a performance cache only. The database is the source of truth.
All cache misses are safe — callers fall back to the DB.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class IOrderCacheRepository(ABC):
    """Redis-backed cache for live OMS state.

    Key namespaces:
      oms:idem:{signal_id}      — idempotency lock (5 min TTL)
      oms:order:{order_id}      — serialised order state (15 min TTL)
      oms:position:{pos_id}     — serialised position state (session TTL)
      oms:active_orders         — sorted set of order_ids by submit time
    """

    @abstractmethod
    async def set_idempotency_key(
        self,
        signal_id: UUID,
        order_id: UUID,
        ttl_seconds: int = 300,
    ) -> bool:
        """Atomically set oms:idem:{signal_id} with SET NX.

        Returns True if the key was set (first time), False if already exists
        (duplicate — OMS must discard the signal).
        """

    @abstractmethod
    async def get_idempotency_order_id(self, signal_id: UUID) -> UUID | None:
        """Return the existing order_id for signal_id, or None."""

    @abstractmethod
    async def cache_order(
        self,
        order_id: UUID,
        order_json: str,
        ttl_seconds: int = 900,
    ) -> None:
        """Store serialised order state in Redis."""

    @abstractmethod
    async def get_cached_order(self, order_id: UUID) -> str | None:
        """Return serialised order JSON or None on cache miss."""

    @abstractmethod
    async def evict_order(self, order_id: UUID) -> None:
        """Remove order from cache (on terminal state)."""

    @abstractmethod
    async def cache_position(
        self,
        position_id: UUID,
        position_json: str,
        ttl_seconds: int = 86400,
    ) -> None:
        """Store serialised position state."""

    @abstractmethod
    async def get_cached_position(self, position_id: UUID) -> str | None:
        """Return serialised position JSON or None on cache miss."""

    @abstractmethod
    async def evict_position(self, position_id: UUID) -> None:
        """Remove position from cache."""
