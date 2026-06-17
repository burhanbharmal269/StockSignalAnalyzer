"""Position entity — tracks an open or closed trading position.

Created when a primary order transitions to FILLED.
Closed when a stop-loss or target order fills, or via time exit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.trading_mode import TradingMode
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


@dataclass
class Position:
    """An open or closed trading position.

    Created when an order transitions to FILLED.
    Closed when a stoploss or target order fills.

    Position sizing comes from Risk Engine. OMS never calculates size.
    """

    position_id: uuid.UUID
    symbol: Symbol
    direction: SignalType
    quantity: int
    entry_price: Price
    current_price: Price

    # Phase 15 enrichment — default-safe for backward compat
    signal_id: uuid.UUID | None = field(default=None)
    order_id: uuid.UUID | None = field(default=None)
    instrument_token: int = field(default=0)
    lots: int = field(default=0)
    stop_loss_price: Price | None = field(default=None)
    target_1_price: Price | None = field(default=None)
    target_2_price: Price | None = field(default=None)
    trading_mode: TradingMode = field(default=TradingMode.LIVE)
    regime_at_open: str = field(default="")
    stop_order_id: uuid.UUID | None = field(default=None)
    target_order_id: uuid.UUID | None = field(default=None)

    # Phase 17 audit fields — nullable for backward compat
    risk_profile_id: uuid.UUID | None = field(default=None)
    allocation_id: uuid.UUID | None = field(default=None)
    portfolio_id: uuid.UUID | None = field(default=None)
    capital_source_mode: CapitalSourceMode | None = field(default=None)
    effective_capital: Decimal | None = field(default=None)
    effective_margin: Decimal | None = field(default=None)

    # Mutable state
    state: PositionState = field(default=PositionState.OPEN)
    realized_pnl: Price = field(default_factory=Price.zero)
    current_mtm_pnl: Price = field(default_factory=Price.zero)
    outcome: PositionOutcome | None = field(default=None)

    # Timestamps
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            msg = f"Position quantity must be > 0, got {self.quantity}"
            raise ValueError(msg)

    # ------------------------------------------------------------------
    # Computed P&L
    # ------------------------------------------------------------------

    @property
    def unrealized_pnl(self) -> Price:
        """Unrealized P&L based on current_price vs entry_price."""
        raw_pnl = (self.current_price - self.entry_price) * self.quantity
        if self.direction == SignalType.SHORT:
            return -raw_pnl
        return raw_pnl

    @property
    def total_pnl(self) -> Price:
        return self.unrealized_pnl + self.realized_pnl

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def update_price(self, new_price: Price) -> None:
        self.current_price = new_price
        raw_pnl = (new_price - self.entry_price) * self.quantity
        self.current_mtm_pnl = -raw_pnl if self.direction == SignalType.SHORT else raw_pnl

    def assign_stop_order(self, stop_order_id: uuid.UUID) -> None:
        self.stop_order_id = stop_order_id

    def assign_target_order(self, target_order_id: uuid.UUID) -> None:
        self.target_order_id = target_order_id

    def close(
        self,
        exit_price: Price,
        closed_quantity: int,
        outcome: PositionOutcome = PositionOutcome.WIN,
    ) -> None:
        """Fully close the position at exit_price."""
        realized = (exit_price - self.entry_price) * closed_quantity
        if self.direction == SignalType.SHORT:
            realized = -realized
        self.realized_pnl = self.realized_pnl + realized
        self.current_price = exit_price
        self.current_mtm_pnl = Price.zero()
        self.state = PositionState.CLOSED
        self.outcome = outcome
        self.closed_at = datetime.now(UTC)

    def partial_close(self, exit_price: Price, closed_quantity: int) -> None:
        """Partially close the position."""
        if closed_quantity >= self.quantity:
            msg = (
                f"Partial close quantity {closed_quantity} >= "
                f"position quantity {self.quantity}"
            )
            raise ValueError(msg)
        realized = (exit_price - self.entry_price) * closed_quantity
        if self.direction == SignalType.SHORT:
            realized = -realized
        self.realized_pnl = self.realized_pnl + realized
        self.quantity -= closed_quantity
        self.state = PositionState.PARTIALLY_CLOSED

    def move_stop_to_breakeven(self) -> None:
        """Move stop-loss price to breakeven (entry price) after T1 hit."""
        self.stop_loss_price = self.entry_price

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def is_stop_hit(self) -> bool:
        if self.stop_loss_price is None:
            return False
        if self.direction == SignalType.LONG:
            return self.current_price <= self.stop_loss_price
        return self.current_price >= self.stop_loss_price

    @property
    def is_target_hit(self) -> bool:
        if self.target_1_price is None:
            return False
        if self.direction == SignalType.LONG:
            return self.current_price >= self.target_1_price
        return self.current_price <= self.target_1_price

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        symbol: Symbol,
        direction: SignalType,
        quantity: int,
        entry_price: Price,
        *,
        signal_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        instrument_token: int = 0,
        lots: int = 0,
        stop_loss_price: Price | None = None,
        target_1_price: Price | None = None,
        target_2_price: Price | None = None,
        trading_mode: TradingMode = TradingMode.LIVE,
        regime_at_open: str = "",
    ) -> Position:
        return cls(
            position_id=uuid.uuid4(),
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            signal_id=signal_id,
            order_id=order_id,
            instrument_token=instrument_token,
            lots=lots,
            stop_loss_price=stop_loss_price,
            target_1_price=target_1_price,
            target_2_price=target_2_price,
            trading_mode=trading_mode,
            regime_at_open=regime_at_open,
        )
