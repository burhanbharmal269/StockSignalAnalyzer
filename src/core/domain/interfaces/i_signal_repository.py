"""ISignalRepository — domain port for signal persistence.

Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from core.domain.entities.signal import Signal
from core.domain.enums.signal_state import SignalState


class ISignalRepository(ABC):
    @abstractmethod
    async def save(self, signal: Signal) -> None:
        """Persist or update a signal."""

    @abstractmethod
    async def get_by_id(self, signal_id: UUID) -> Signal | None:
        """Return signal by primary key, or None."""

    @abstractmethod
    async def get_by_state(self, state: SignalState) -> list[Signal]:
        """Return all signals in a given state."""

    @abstractmethod
    async def get_active(self) -> list[Signal]:
        """Return signals that are not in a terminal state."""
