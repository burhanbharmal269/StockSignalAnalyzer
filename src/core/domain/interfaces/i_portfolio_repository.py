"""IPortfolioRepository — persistence contract for Portfolio entities."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from core.domain.entities.portfolio import Portfolio
from core.domain.enums.portfolio_type import PortfolioType


class IPortfolioRepository(ABC):
    @abstractmethod
    async def save(self, portfolio: Portfolio) -> None: ...

    @abstractmethod
    async def get_by_id(self, portfolio_id: uuid.UUID) -> Portfolio | None: ...

    @abstractmethod
    async def get_active(self) -> Portfolio | None: ...

    @abstractmethod
    async def get_active_by_type(self, portfolio_type: PortfolioType) -> Portfolio | None: ...

    @abstractmethod
    async def list_all(self) -> list[Portfolio]: ...

    @abstractmethod
    async def deactivate_all(self) -> None:
        """Set is_active=False on every portfolio."""
        ...
