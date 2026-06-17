"""ExecutionReport — broker's view of an order execution.

Received from broker webhooks or polling. The OMS translates this into
Fill objects and updates Order state accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.domain.value_objects.price import Price


@dataclass(frozen=True)
class ExecutionReport:
    """Broker execution update for an order.

    Produced by the broker adapter when it receives an order status update.
    The OMS consumes ExecutionReport to drive Order state transitions.
    """

    broker_order_id: str
    oms_order_id: str   # UUID as string — broker doesn't know our UUID
    status: str         # broker-native status string (mapped to OrderState by OMS)
    filled_quantity: int
    remaining_quantity: int
    average_fill_price: Price | None
    last_fill_price: Price | None
    last_fill_quantity: int
    exchange_trade_id: str
    reported_at: datetime
    rejection_reason: str = ""
    trading_mode: str = "LIVE"

    @property
    def is_fully_filled(self) -> bool:
        return self.remaining_quantity == 0 and self.filled_quantity > 0

    @property
    def is_partial_fill(self) -> bool:
        return self.filled_quantity > 0 and self.remaining_quantity > 0

    @property
    def is_rejected(self) -> bool:
        return self.status in ("REJECTED", "CANCELLED", "EXPIRED")
