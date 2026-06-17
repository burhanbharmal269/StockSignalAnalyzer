"""ICapitalAllocationRepository — persistence contract for CapitalAllocation entities."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from core.domain.entities.capital_allocation import CapitalAllocation


class ICapitalAllocationRepository(ABC):
    @abstractmethod
    async def save(self, allocation: CapitalAllocation) -> None: ...

    @abstractmethod
    async def get_by_id(self, allocation_id: uuid.UUID) -> CapitalAllocation | None: ...

    @abstractmethod
    async def get_active(self) -> CapitalAllocation | None: ...

    @abstractmethod
    async def list_all(self) -> list[CapitalAllocation]: ...

    @abstractmethod
    async def deactivate_all(self) -> None:
        """Set is_active=False on every allocation."""
        ...

    @abstractmethod
    async def append_history(
        self,
        allocation_id: uuid.UUID,
        change_type: str,
        previous_capital: object,
        new_capital: object,
        changed_by: str = "system",
        notes: str = "",
    ) -> None:
        """Append to allocation_history — never updates an existing row."""
        ...
