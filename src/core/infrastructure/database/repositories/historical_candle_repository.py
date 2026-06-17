"""SQLAlchemy repository for historical_candles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.historical_candle import HistoricalCandle
from core.domain.interfaces.i_historical_candle_repository import IHistoricalCandleRepository
from decimal import Decimal


class SqlAlchemyHistoricalCandleRepository(IHistoricalCandleRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert_many(self, candles: list[HistoricalCandle]) -> int:
        if not candles:
            return 0
        async with self._sf() as db:
            rows = [
                {
                    "symbol": c.symbol, "timeframe": c.timeframe,
                    "ts": c.ts,
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": c.volume, "oi": c.oi,
                }
                for c in candles
            ]
            stmt = text("""
                INSERT INTO historical_candles
                    (symbol, timeframe, ts, open, high, low, close, volume, oi)
                VALUES
                    (:symbol, :timeframe, :ts, :open, :high, :low, :close, :volume, :oi)
                ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume, oi=EXCLUDED.oi
            """)
            for row in rows:
                await db.execute(stmt, row)
            await db.commit()
        return len(candles)

    async def get(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]:
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT symbol, timeframe, ts, open, high, low, close, volume, oi
                    FROM historical_candles
                    WHERE symbol=:sym AND timeframe=:tf
                      AND ts >= :from_dt AND ts <= :to_dt
                    ORDER BY ts ASC
                """),
                {"sym": symbol, "tf": timeframe, "from_dt": from_dt, "to_dt": to_dt},
            )
            return [_row_to_candle(r) for r in result.fetchall()]

    async def get_latest(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[HistoricalCandle]:
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT symbol, timeframe, ts, open, high, low, close, volume, oi
                    FROM historical_candles
                    WHERE symbol=:sym AND timeframe=:tf
                    ORDER BY ts DESC LIMIT :lim
                """),
                {"sym": symbol, "tf": timeframe, "lim": limit},
            )
            rows = result.fetchall()
            return [_row_to_candle(r) for r in reversed(rows)]

    async def last_stored_ts(
        self, symbol: str, timeframe: str
    ) -> datetime | None:
        async with self._sf() as db:
            result = await db.execute(
                text("SELECT MAX(ts) FROM historical_candles WHERE symbol=:sym AND timeframe=:tf"),
                {"sym": symbol, "tf": timeframe},
            )
            val = result.scalar()
            return val

    async def symbols_in_range(
        self, timeframe: str, from_dt: datetime, to_dt: datetime
    ) -> list[str]:
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT DISTINCT symbol FROM historical_candles
                    WHERE timeframe=:tf AND ts>=:from_dt AND ts<=:to_dt
                """),
                {"tf": timeframe, "from_dt": from_dt, "to_dt": to_dt},
            )
            return [r[0] for r in result.fetchall()]


def _row_to_candle(r) -> HistoricalCandle:
    return HistoricalCandle(
        symbol=r[0], timeframe=r[1], ts=r[2],
        open=Decimal(str(r[3])), high=Decimal(str(r[4])),
        low=Decimal(str(r[5])), close=Decimal(str(r[6])),
        volume=int(r[7] or 0), oi=int(r[8] or 0),
    )
