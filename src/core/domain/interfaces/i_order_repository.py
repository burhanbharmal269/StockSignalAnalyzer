"""IOrderRepository — domain port for order persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from core.domain.entities.order import Order
from core.domain.enums.order_state import OrderState


class IOrderRepository(ABC):
    @abstractmethod
    async def save(self, order: Order) -> None:
        """Persist or update an order."""

    @abstractmethod
    async def get_by_id(self, order_id: UUID) -> Order | None:
        """Return order by primary key, or None."""

    @abstractmethod
    async def get_by_signal_id(self, signal_id: UUID) -> list[Order]:
        """Return all orders created from a signal."""

    @abstractmethod
    async def get_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        """Return order by broker-assigned ID."""

    @abstractmethod
    async def get_by_state(self, state: OrderState) -> list[Order]:
        """Return all orders in a given state."""

    @abstractmethod
    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Order]:
        """Return orders sorted by created_at descending with pagination."""
