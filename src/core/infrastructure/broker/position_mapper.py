"""PositionMapper — translates BrokerPosition to OMS-compatible fields.

The OMS Position entity owns the authoritative position state.
This mapper is used for reconciliation and display; it never mutates OMS positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.value_objects.broker_dtos import BrokerPosition


@dataclass(frozen=True)
class PositionSnapshot:
    """OMS-compatible view of a broker position (read-only)."""

    symbol: str
    exchange: str
    product: str
    quantity: int
    net_quantity: int
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal
    is_long: bool


class PositionMapper:
    """Stateless mapper: BrokerPosition → PositionSnapshot."""

    @staticmethod
    def to_snapshot(broker_pos: BrokerPosition) -> PositionSnapshot:
        """Convert a BrokerPosition to a PositionSnapshot for reconciliation use."""
        net_qty = (
            broker_pos.net_quantity
            if broker_pos.net_quantity is not None
            else broker_pos.quantity
        )
        return PositionSnapshot(
            symbol=broker_pos.symbol,
            exchange=broker_pos.exchange,
            product=broker_pos.product,
            quantity=broker_pos.quantity,
            net_quantity=net_qty,
            average_price=broker_pos.average_price,
            last_price=broker_pos.last_price,
            pnl=broker_pos.pnl,
            is_long=net_qty >= 0,
        )

    @staticmethod
    def to_snapshots(broker_positions: list[BrokerPosition]) -> list[PositionSnapshot]:
        """Batch convert a list of BrokerPositions."""
        return [PositionMapper.to_snapshot(p) for p in broker_positions]
