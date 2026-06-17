"""IPositionRepository — domain port for position persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from core.domain.entities.position import Position
from core.domain.value_objects.symbol import Symbol


class IPositionRepository(ABC):
    @abstractmethod
    async def save(self, position: Position) -> None:
        """Persist or update a position."""

    @abstractmethod
    async def get_by_id(self, position_id: UUID) -> Position | None:
        """Return position by primary key, or None."""

    @abstractmethod
    async def get_open_positions(self) -> list[Position]:
        """Return all positions in OPEN or PARTIALLY_CLOSED state."""

    @abstractmethod
    async def get_by_symbol(self, symbol: Symbol) -> list[Position]:
        """Return all positions for a symbol (open and closed)."""
