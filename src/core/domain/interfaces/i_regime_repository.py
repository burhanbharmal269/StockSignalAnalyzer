"""IRegimeRepository — persistence contract for RegimeSnapshot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.regime_snapshot import RegimeSnapshot


class IRegimeRepository(ABC):
    """Append-only store for RegimeSnapshot records."""

    @abstractmethod
    async def save(self, snapshot: RegimeSnapshot) -> None:
        """Persist a regime snapshot. Implementations must be append-only."""

    @abstractmethod
    async def get_latest(
        self,
        instrument_token: int,
        timeframe: str,
    ) -> RegimeSnapshot | None:
        """Return the most recent snapshot for (instrument_token, timeframe)."""

    @abstractmethod
    async def get_history(
        self,
        instrument_token: int,
        timeframe: str,
        since: datetime,
    ) -> list[RegimeSnapshot]:
        """Return all snapshots for the given instrument/timeframe after *since*."""
