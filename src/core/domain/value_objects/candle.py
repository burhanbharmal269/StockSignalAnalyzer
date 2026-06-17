"""Candle — completed OHLCV bar for one instrument and time interval.

Produced by CandleAggregatorService when an interval boundary is crossed.
Published as CandleClosedEvent to the event bus.

Reference: docs/12_WEBSOCKET_MANAGER.md §Candle Aggregation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    """Completed OHLCV bar.

    All prices are Decimal. Timestamps are UTC-aware.
    ``open_interest`` is None for equity instruments — never defaulted to 0.
    """

    instrument_token: int
    tradingsymbol: str
    exchange: str
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    opened_at: datetime
    closed_at: datetime
    open_interest: int | None = None
