"""OHLC — open/high/low/close price bundle for a single bar or tick.

Reference: docs/12_WEBSOCKET_MANAGER.md §Message Normalization
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OHLC:
    """Immutable OHLC price quad.

    All values are Decimal to avoid floating-point precision loss.
    Present in QUOTE-mode and FULL-mode ticks; absent in LTP-mode ticks.
    """

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
