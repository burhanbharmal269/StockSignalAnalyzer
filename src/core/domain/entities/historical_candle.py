"""HistoricalCandle — OHLCV + OI data point for a symbol/timeframe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class HistoricalCandle:
    symbol: str
    timeframe: str       # 1m 3m 5m 15m 30m 60m D W M
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    oi: int = 0

    @property
    def typical_price(self) -> Decimal:
        return (self.high + self.low + self.close) / 3

    @property
    def body_size(self) -> Decimal:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open
