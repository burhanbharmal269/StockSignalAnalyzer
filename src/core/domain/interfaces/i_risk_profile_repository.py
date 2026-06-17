"""IRiskProfileRepository — persistence contract for RiskProfile entities."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from core.domain.entities.risk_profile import RiskProfile


class IRiskProfileRepository(ABC):
    @abstractmethod
    async def save(self, profile: RiskProfile) -> None: ...

    @abstractmethod
    async def get_by_id(self, profile_id: uuid.UUID) -> RiskProfile | None: ...

    @abstractmethod
    async def get_active(self) -> RiskProfile | None: ...

    @abstractmethod
    async def list_all(self) -> list[RiskProfile]: ...

    @abstractmethod
    async def deactivate_all(self) -> None:
        """Set is_active=False on every profile (used before activating a new one)."""
        ...
