"""Broker data transfer objects — broker-agnostic return types for IBroker.

These are pure value objects. No broker SDK types ever appear here.
All prices are Decimal; all timestamps are UTC-aware.

Reference: docs/04_BROKER_ABSTRACTION.md, docs/09_CLAUDE_EXECUTION_RULES.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class BrokerOrderRequest:
    """Parameters for submitting an order through IBroker.

    ``product`` uses internal terms (INTRADAY / OVERNIGHT / DELIVERY).
    Each broker adapter maps these to its own product codes (e.g. MIS/NRML/CNC
    for Kite). No broker-specific strings ever appear here.

    ``order_type`` uses internal terms: MARKET, LIMIT, SL_LIMIT, SL_MARKET.
    """

    symbol: str
    exchange: str
    direction: str
    quantity: int
    order_type: str
    product: str
    limit_price: Decimal | None = None
    trigger_price: Decimal | None = None
    tag: str = ""


@dataclass(frozen=True)
class BrokerPosition:
    """Snapshot of one open position returned by the broker."""

    symbol: str
    exchange: str
    product: str
    quantity: int
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal
    day_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    net_quantity: int | None = None  # signed: positive=long, negative=short


@dataclass(frozen=True)
class BrokerHolding:
    """Snapshot of one delivery holding returned by the broker."""

    symbol: str
    exchange: str
    isin: str
    quantity: int
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class BrokerOrder:
    """Snapshot of one order returned by the broker's order book."""

    broker_order_id: str
    symbol: str
    exchange: str
    direction: str
    quantity: int
    filled_quantity: int
    status: str
    order_type: str
    product: str
    limit_price: Decimal | None
    average_price: Decimal | None
    placed_at: datetime


@dataclass(frozen=True)
class BrokerTrade:
    """Snapshot of one executed trade returned by the broker."""

    trade_id: str
    broker_order_id: str
    symbol: str
    exchange: str
    direction: str
    quantity: int
    price: Decimal
    traded_at: datetime


@dataclass(frozen=True)
class BrokerProfile:
    """Authenticated user profile from the broker."""

    user_id: str
    full_name: str
    email: str
    broker_name: str


@dataclass(frozen=True)
class BrokerMargin:
    """Available and used margin from the broker."""

    available_cash: Decimal
    used_margin: Decimal
    total_margin: Decimal
    segment: str = "equity"
    exposure_margin: Decimal = field(default_factory=lambda: Decimal("0"))
    span_margin: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass(frozen=True)
class OptionChainEntry:
    """Single strike entry in an option chain snapshot.

    For option entries (option_type CE/PE): all fields apply as documented.
    For futures entries (option_type FUT): strike is 0, change_in_oi is 0;
    tradingsymbol, oi_day_high, oi_day_low are populated.
    """

    symbol: str
    exchange: str
    expiry: date
    strike: Decimal
    option_type: str
    last_price: Decimal
    open_interest: int
    change_in_oi: int
    volume: int
    instrument_token: int
    iv: Decimal | None = None
    tradingsymbol: str = ""   # NFO tradingsymbol, e.g. "RELIANCE26JULFUT" (FUT only)
    oi_day_high: int = 0      # Daily OI high from Kite quote (FUT only, informational)
    oi_day_low: int = 0       # Daily OI low from Kite quote (FUT only, informational)
