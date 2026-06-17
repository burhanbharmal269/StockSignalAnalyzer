"""Domain events for the OMS order and position lifecycle.

Every event is an immutable fact. All state transitions produce an event.
Events are appended to order_events hypertable (TimescaleDB).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.events.base import DomainEvent


# ──────────────────────────────────────────────────────────────────────────────
# Order lifecycle events
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class OrderCreated(DomainEvent):
    """OMS created an order from a SignalRiskApproved event."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    instrument_token: int
    underlying: str
    tradingsymbol: str
    direction: str
    quantity: int
    lots: int
    order_type: str
    transaction_type: str
    product: str
    trading_mode: str


@dataclass(frozen=True, kw_only=True)
class OrderValidated(DomainEvent):
    """Order passed all pre-submission checks (TTL, kill switch, rate limit, dedup)."""

    order_id: uuid.UUID
    signal_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class OrderRouted(DomainEvent):
    """Order was submitted to the broker (broker API call succeeded)."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    broker_order_id: str
    broker_name: str


@dataclass(frozen=True, kw_only=True)
class OrderSubmitted(DomainEvent):
    """Broker acknowledged the order (exchange accepted it)."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    symbol: str
    broker_order_id: str


@dataclass(frozen=True, kw_only=True)
class OrderFilled(DomainEvent):
    """Order was fully executed at the exchange."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    filled_quantity: int
    average_fill_price: Decimal
    filled_at: datetime


@dataclass(frozen=True, kw_only=True)
class OrderPartiallyFilled(DomainEvent):
    """Order was partially executed. Remainder remains open."""

    order_id: uuid.UUID
    filled_quantity: int
    remaining_quantity: int
    average_fill_price: Decimal


@dataclass(frozen=True, kw_only=True)
class OrderCancelled(DomainEvent):
    """Order was cancelled by OMS, operator, or kill switch."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    reason: str
    cancelled_by: str = "oms"


@dataclass(frozen=True, kw_only=True)
class OrderRejected(DomainEvent):
    """Order was rejected by OMS pre-submission checks or by the broker/exchange."""

    order_id: uuid.UUID
    signal_id: uuid.UUID
    reason: str
    rejected_by: str = "oms"  # "oms" | "broker" | "exchange"


@dataclass(frozen=True, kw_only=True)
class OrderExpired(DomainEvent):
    """Order was not filled before market close."""

    order_id: uuid.UUID
    signal_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class OrderIdempotencyBlocked(DomainEvent):
    """Duplicate signal_id detected — second order silently discarded."""

    signal_id: uuid.UUID
    original_order_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class OrderKillSwitchBlocked(DomainEvent):
    """Order rejected because kill switch is active."""

    signal_id: uuid.UUID
    kill_switch_activated_at: datetime


@dataclass(frozen=True, kw_only=True)
class OrderTtlExpired(DomainEvent):
    """Signal TTL expired before order could be submitted."""

    signal_id: uuid.UUID
    signal_valid_until: datetime


# ──────────────────────────────────────────────────────────────────────────────
# Position lifecycle events
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class PositionOpened(DomainEvent):
    """A new position was opened when the primary order filled."""

    position_id: uuid.UUID
    order_id: uuid.UUID
    signal_id: uuid.UUID
    instrument_token: int
    underlying: str
    direction: str
    lots: int
    quantity: int
    entry_price: Decimal
    stop_loss_price: Decimal
    target_1_price: Decimal
    trading_mode: str
    regime_at_open: str


@dataclass(frozen=True, kw_only=True)
class PositionClosed(DomainEvent):
    """Position was fully closed."""

    position_id: uuid.UUID
    signal_id: uuid.UUID
    direction: str
    entry_price: Decimal
    exit_price: Decimal
    lots: int
    realized_pnl: Decimal
    outcome: str    # WIN | LOSS | TIME_EXIT | BREAKEVEN
    trading_mode: str


@dataclass(frozen=True, kw_only=True)
class StopLossTriggered(DomainEvent):
    """Stop-loss order filled — position closed at stop."""

    position_id: uuid.UUID
    stop_order_id: uuid.UUID
    signal_id: uuid.UUID
    stop_price: Decimal
    fill_price: Decimal


@dataclass(frozen=True, kw_only=True)
class TargetTriggered(DomainEvent):
    """Target order filled — position closed at target."""

    position_id: uuid.UUID
    target_order_id: uuid.UUID
    signal_id: uuid.UUID
    target_price: Decimal
    fill_price: Decimal
    target_level: int = 1   # 1 = T1, 2 = T2


@dataclass(frozen=True, kw_only=True)
class StopLossPlaced(DomainEvent):
    """Stop-loss order was placed after primary order filled."""

    position_id: uuid.UUID
    stop_order_id: uuid.UUID
    signal_id: uuid.UUID
    trigger_price: Decimal


@dataclass(frozen=True, kw_only=True)
class TargetPlaced(DomainEvent):
    """Target order was placed after primary order filled."""

    position_id: uuid.UUID
    target_order_id: uuid.UUID
    signal_id: uuid.UUID
    limit_price: Decimal
    target_level: int = 1


# ──────────────────────────────────────────────────────────────────────────────
# Reconciliation events
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ReconciliationCompleted(DomainEvent):
    """Reconciliation pass completed."""

    orders_checked: int
    positions_checked: int
    discrepancies_found: int
    rogue_orders_found: int


@dataclass(frozen=True, kw_only=True)
class ReconciliationDiscrepancyDetected(DomainEvent):
    """A mismatch between OMS and broker state was found."""

    order_id: uuid.UUID | None
    broker_order_id: str
    discrepancy_type: str   # "MISSING_ORDER" | "ORPHAN_POSITION" | "QTY_MISMATCH"
    oms_state: str
    broker_state: str
    detail: str = ""
