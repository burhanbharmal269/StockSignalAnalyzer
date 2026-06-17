"""HistoricalDataService — collect and serve historical OHLCV data.

Fetches from Kite (primary) with NSE fallback, stores in historical_candles.
Supports gap-filling: only requests candles newer than what's already stored.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle
    from core.domain.interfaces.i_historical_candle_repository import IHistoricalCandleRepository
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider

_log = logging.getLogger(__name__)

SUPPORTED_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "60m", "D"]

# How far back to initially collect for each timeframe
_INITIAL_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 30, "3m": 60, "5m": 90, "15m": 180,
    "30m": 365, "60m": 730, "D": 1825,   # 5 years for daily
}


class HistoricalDataService:
    def __init__(
        self,
        repository: IHistoricalCandleRepository,
        primary_provider: IMarketDataProvider,
        fallback_provider: IMarketDataProvider,
    ) -> None:
        self._repo = repository
        self._primary = primary_provider
        self._fallback = fallback_provider

    async def fetch_and_store(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> int:
        """Fetch candles from provider and persist. Returns count stored."""
        to_dt = to_dt or datetime.now(UTC)

        if from_dt is None:
            last_ts = await self._repo.last_stored_ts(symbol, timeframe)
            if last_ts:
                from_dt = last_ts + timedelta(minutes=1)
            else:
                days = _INITIAL_LOOKBACK_DAYS.get(timeframe, 365)
                from_dt = to_dt - timedelta(days=days)

        if from_dt >= to_dt:
            return 0

        candles = await self._fetch(symbol, timeframe, from_dt, to_dt)
        if not candles:
            return 0

        stored = await self._repo.upsert_many(candles)
        _log.info(
            "historical_data.stored symbol=%s tf=%s count=%d",
            symbol, timeframe, stored,
        )
        return stored

    async def get(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]:
        return await self._repo.get(symbol, timeframe, from_dt, to_dt)

    async def get_latest(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> list[HistoricalCandle]:
        return await self._repo.get_latest(symbol, timeframe, limit)

    async def bulk_fetch(
        self,
        symbols: list[str],
        timeframes: list[str] | None = None,
    ) -> dict[str, int]:
        """Fetch and store for multiple symbols. Returns {symbol: candles_stored}."""
        timeframes = timeframes or ["15m", "60m", "D"]
        results: dict[str, int] = {}
        for symbol in symbols:
            total = 0
            for tf in timeframes:
                try:
                    count = await self.fetch_and_store(symbol, tf)
                    total += count
                except Exception as exc:
                    _log.warning("bulk_fetch failed %s %s: %s", symbol, tf, exc)
            results[symbol] = total
        return results

    async def _fetch(
        self, symbol: str, timeframe: str, from_dt: datetime, to_dt: datetime
    ) -> list[HistoricalCandle]:
        try:
            candles = await self._primary.get_historical_candles(
                symbol, timeframe, from_dt, to_dt
            )
            if candles:
                return candles
        except Exception as exc:
            _log.warning("primary provider failed %s %s: %s", symbol, timeframe, exc)

        try:
            return await self._fallback.get_historical_candles(
                symbol, timeframe, from_dt, to_dt
            )
        except Exception as exc:
            _log.warning("fallback provider failed %s %s: %s", symbol, timeframe, exc)
            return []
