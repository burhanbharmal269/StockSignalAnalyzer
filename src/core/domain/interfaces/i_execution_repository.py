"""IExecutionRepository — domain port for fill/execution persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from core.domain.value_objects.fill import Fill


class IExecutionRepository(ABC):
    @abstractmethod
    async def save(self, fill: Fill) -> None:
        """Persist a fill record."""

    @abstractmethod
    async def get_by_order_id(self, order_id: UUID) -> list[Fill]:
        """Return all fills for an order, oldest first."""

    @abstractmethod
    async def get_by_id(self, fill_id: UUID) -> Fill | None:
        """Return a fill by primary key."""
