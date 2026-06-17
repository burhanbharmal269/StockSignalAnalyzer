"""Fill — a single executed trade at the exchange."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.domain.value_objects.price import Price


@dataclass(frozen=True)
class Fill:
    """Represents one execution (fill) at the exchange.

    A single order may produce multiple fills (partial executions).
    """

    fill_id: uuid.UUID
    order_id: uuid.UUID
    broker_order_id: str
    filled_quantity: int
    fill_price: Price
    fill_time: datetime
    exchange_trade_id: str = ""
    trading_mode: str = "LIVE"

    def __post_init__(self) -> None:
        if self.filled_quantity <= 0:
            msg = f"Fill quantity must be > 0, got {self.filled_quantity}"
            raise ValueError(msg)

    @classmethod
    def create(
        cls,
        order_id: uuid.UUID,
        broker_order_id: str,
        filled_quantity: int,
        fill_price: Price,
        fill_time: datetime | None = None,
        exchange_trade_id: str = "",
        trading_mode: str = "LIVE",
    ) -> Fill:
        return cls(
            fill_id=uuid.uuid4(),
            order_id=order_id,
            broker_order_id=broker_order_id,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            fill_time=fill_time or datetime.now(UTC),
            exchange_trade_id=exchange_trade_id,
            trading_mode=trading_mode,
        )
