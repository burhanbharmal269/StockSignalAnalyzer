"""IBrokerExecutionMonitor — domain port for live broker execution monitoring."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.broker_dtos import BrokerMargin, BrokerPosition
    from core.domain.value_objects.execution_report import ExecutionReport


class IBrokerExecutionMonitor(ABC):
    """Polls the broker for execution updates and translates to domain events.

    Implementations call the broker API and translate raw broker data into
    ExecutionReport / BrokerPosition / BrokerMargin objects.
    The application layer depends only on this interface.
    """

    @abstractmethod
    async def monitor_orders(self, session: object) -> list[ExecutionReport]:
        """Poll broker orders and return ExecutionReports for changed statuses."""

    @abstractmethod
    async def monitor_positions(self, session: object) -> list[BrokerPosition]:
        """Return current broker position snapshots."""

    @abstractmethod
    async def monitor_margin(self, session: object) -> BrokerMargin:
        """Return current broker margin snapshot."""
