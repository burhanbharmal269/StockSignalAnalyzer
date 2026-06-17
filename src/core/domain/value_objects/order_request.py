"""OrderRequest — input to the OMS from a SignalRiskApproved event.

Constructed by OrderManagementService from the SignalRiskApproved event payload.
Contains everything the OMS needs to create, validate, and route the order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class OrderRequest:
    """All fields required to create and route an order.

    Sourced from SignalRiskApproved event (Phase 14 output).
    OMS never calculates position size — it comes from Risk Engine.
    """

    signal_id: uuid.UUID
    instrument_token: int
    underlying: str
    tradingsymbol: str
    exchange: str
    direction: str              # "LONG" | "SHORT"
    strategy_type: str
    regime: str
    position_size_lots: int     # from Risk Engine (never recalculated by OMS)
    lot_size: int
    entry_price: Decimal
    stop_loss_price: Decimal
    target_1_price: Decimal
    target_2_price: Decimal | None
    option_premium: Decimal | None
    risk_decision_id: int | None
    adjusted_score: float
    final_confidence: float
    valid_until: datetime
    trading_mode: str = "LIVE"
    correlation_id: str = ""

    @property
    def quantity(self) -> int:
        return self.position_size_lots * self.lot_size

    @property
    def is_expired(self) -> bool:
        from datetime import UTC
        return datetime.now(UTC) >= self.valid_until

    @property
    def is_long(self) -> bool:
        return self.direction == "LONG"
