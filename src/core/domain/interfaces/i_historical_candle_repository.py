"""IHistoricalCandleRepository — storage abstraction for OHLCV data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class IHistoricalCandleRepository(ABC):
    @abstractmethod
    async def upsert_many(self, candles: list[HistoricalCandle]) -> int: ...

    @abstractmethod
    async def get(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]: ...

    @abstractmethod
    async def get_latest(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[HistoricalCandle]: ...

    @abstractmethod
    async def last_stored_ts(
        self, symbol: str, timeframe: str
    ) -> datetime | None: ...

    @abstractmethod
    async def symbols_in_range(
        self, timeframe: str, from_dt: datetime, to_dt: datetime
    ) -> list[str]: ...
