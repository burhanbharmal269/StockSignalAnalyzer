"""IUniverseRepository — persistence interface for Universe Selection Engine output.

The Redis implementation writes to:
  universe:selected                        → current selected candidate list (JSON)
  universe:metadata:{instrument_token}     → per-instrument filter stage results (Hash)

Both keys share the same TTL: evaluation_interval_seconds + 60s buffer.

Reference: docs/architecture_decisions/AD-USE-01.md (Redis Key Usage)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.domain.events.universe_events import UniverseSelected


class IUniverseRepository(ABC):

    @abstractmethod
    async def save_selected(self, event: UniverseSelected, ttl_seconds: int) -> None:
        """Persist the selected candidate list and per-instrument metadata to Redis.

        Writes:
          universe:selected            → serialised UniverseSelected payload
          universe:metadata:<token>    → Hash with filter_metadata per instrument
        """

    @abstractmethod
    async def get_selected(self) -> UniverseSelected | None:
        """Read the most-recently persisted UniverseSelected event.

        Returns None when the key is absent (first cycle, not yet evaluated)
        or when the key has expired (stale universe).
        """
