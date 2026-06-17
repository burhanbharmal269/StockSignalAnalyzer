"""MarketDepth — 5-level bid/ask order book snapshot.

Reference: docs/12_WEBSOCKET_MANAGER.md §Message Normalization
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DepthLevel:
    """One price level in the order book."""

    price: Decimal
    quantity: int
    orders: int


@dataclass(frozen=True)
class MarketDepth:
    """Immutable 5-level market depth snapshot.

    Present only in FULL-mode ticks; absent in LTP and QUOTE ticks.
    buy[0] is the best bid; sell[0] is the best ask.
    """

    buy: tuple[DepthLevel, ...]   # 5 levels, best-to-worst bid
    sell: tuple[DepthLevel, ...]  # 5 levels, best-to-worst ask
