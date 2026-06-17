"""IOrderRouter — domain port for broker order submission.

Sits between OMS and IBroker. Responsible for broker selection and
translating OMS Order objects into broker-specific requests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.domain.entities.order import Order
from core.domain.value_objects.execution_report import ExecutionReport


class IOrderRouter(ABC):
    """Routes an order to the appropriate broker.

    OMS calls route() after persisting the order.
    The router selects the broker (live vs paper) and calls IBroker.place_order().
    """

    @abstractmethod
    async def route(self, order: Order) -> str:
        """Submit order to broker. Returns broker_order_id.

        Raises:
            BrokerUnavailableError: If broker is unreachable (fail closed).
            BrokerOrderError: If broker rejects the order.
        """

    @abstractmethod
    async def cancel(self, order: Order) -> None:
        """Cancel an open order at the broker.

        Cancellations bypass the kill switch check (Doc 14/22).

        Raises:
            BrokerUnavailableError: If broker is unreachable.
        """

    @abstractmethod
    async def get_order_status(self, broker_order_id: str) -> ExecutionReport | None:
        """Fetch current execution status from broker. Returns None if unknown."""
