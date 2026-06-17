"""TickReceivedEvent — normalized market data tick from any broker WebSocket.

Reference: docs/12_WEBSOCKET_MANAGER.md §Message Normalization
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.events.base import DomainEvent
from core.domain.value_objects.market_depth import MarketDepth
from core.domain.value_objects.ohlc import OHLC


@dataclass(frozen=True)
class TickReceivedEvent(DomainEvent):
    """A single normalized tick published to market_data.tick.received.

    Normalization rules (enforced by the broker adapter, not here):
    - All prices are Decimal (never float).
    - All timestamps are UTC-aware.
    - open_interest is None for equity ticks — never defaulted to 0.
    - ohlc and depth are None for LTP-mode ticks.
    """

    instrument_token: int = 0
    tradingsymbol: str = ""
    exchange: str = ""                     # Exchange enum introduced in Sprint 5
    last_price: Decimal = field(default_factory=lambda: Decimal("0"))
    last_quantity: int = 0
    buy_quantity: int = 0
    sell_quantity: int = 0
    volume: int = 0
    open_interest: int | None = None       # None for equity — never default to 0
    change: Decimal = field(default_factory=lambda: Decimal("0"))
    last_trade_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    ohlc: OHLC | None = None               # None in LTP mode
    depth: MarketDepth | None = None       # None unless FULL mode
