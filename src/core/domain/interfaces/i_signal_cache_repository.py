"""ISignalCacheRepository — domain port for signal Redis cache operations.

Covers deduplication keys and active-signal metadata. The persistence layer
(ISignalRepository) handles durable DB storage; this interface covers the
ephemeral Redis layer only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ISignalCacheRepository(ABC):
    """Redis-backed cache operations for signal deduplication and active tracking."""

    @abstractmethod
    async def is_duplicate(self, dedup_key: str) -> bool:
        """Return True if a dedup key already exists in Redis."""

    @abstractmethod
    async def set_dedup(
        self, dedup_key: str, signal_id: str, ttl_seconds: int
    ) -> None:
        """Write a dedup key with the given TTL.

        Call AFTER the signal has been persisted to the DB (persistence-first).
        """

    @abstractmethod
    async def get_active_signal_id(self, instrument_token: int) -> str | None:
        """Return the signal_id string of the active signal for a token, or None."""

    @abstractmethod
    async def set_active_signal(
        self, instrument_token: int, signal_id: str, ttl_seconds: int
    ) -> None:
        """Cache the active signal id for a given instrument token."""

    @abstractmethod
    async def delete_active_signal(self, instrument_token: int) -> None:
        """Remove the active signal cache entry for an instrument."""
