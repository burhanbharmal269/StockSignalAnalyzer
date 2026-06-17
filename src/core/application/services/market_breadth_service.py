"""MarketBreadthService — advance/decline ratio, 52W highs/lows, sector strength."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from core.application.services.market_data.live_feed_service import LiveMarketFeedService
    from core.infrastructure.database.repositories.market_universe_repository import (
        SqlAlchemyMarketUniverseRepository,
    )
    from core.infrastructure.database.repositories.historical_candle_repository import (
        SqlAlchemyHistoricalCandleRepository,
    )

_log = logging.getLogger(__name__)


class MarketBreadthService:
    def __init__(
        self,
        universe_repo: SqlAlchemyMarketUniverseRepository,
        candle_repo: SqlAlchemyHistoricalCandleRepository,
        live_feed: LiveMarketFeedService,
        session_factory,
    ) -> None:
        self._universe = universe_repo
        self._candles = candle_repo
        self._feed = live_feed
        self._sf = session_factory

    async def calculate_and_store(self) -> dict:
        """Calculate current market breadth and persist snapshot."""
        symbols = await self._universe.get_active(segment="EQ", fo_only=True)
        sym_list = [s.symbol for s in symbols]

        advances = declines = unchanged = 0
        new_highs = new_lows = 0
        above_200 = 0
        sector_data: dict = {}

        for sym in sym_list[:200]:    # cap for performance
            try:
                # Get last 2 daily candles for advance/decline
                daily = await self._candles.get_latest(sym, "D", limit=250)
                if len(daily) < 2:
                    continue

                prev_close = daily[-2].close
                last_close = daily[-1].close

                if last_close > prev_close:
                    advances += 1
                elif last_close < prev_close:
                    declines += 1
                else:
                    unchanged += 1

                # 52-week high/low
                if len(daily) >= 250:
                    year_high = max(c.high for c in daily[-250:])
                    year_low = min(c.low for c in daily[-250:])
                    if last_close >= year_high:
                        new_highs += 1
                    elif last_close <= year_low:
                        new_lows += 1

                # 200 DMA
                if len(daily) >= 200:
                    dma200 = sum(c.close for c in daily[-200:]) / 200
                    if last_close > dma200:
                        above_200 += 1

            except Exception:
                pass

        total = advances + declines + unchanged or 1
        ad_ratio = advances / max(declines, 1)
        breadth_score = ((advances - declines) / total) * 100
        above_200_pct = (above_200 / max(len(sym_list[:200]), 1)) * 100

        snapshot = {
            "ts": datetime.now(UTC).isoformat(),
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "new_highs_52w": new_highs,
            "new_lows_52w": new_lows,
            "advance_decline_ratio": round(ad_ratio, 3),
            "breadth_score": round(breadth_score, 2),
            "above_200dma_pct": round(above_200_pct, 2),
            "total_tracked": len(sym_list[:200]),
        }

        await self._persist(snapshot)
        return snapshot

    async def get_latest(self) -> dict | None:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT ts, advances, declines, unchanged, new_highs_52w,
                       new_lows_52w, advance_decline_ratio, breadth_score,
                       above_200dma_pct, sector_data
                FROM market_breadth_snapshots
                ORDER BY ts DESC LIMIT 1
            """))
            row = result.mappings().fetchone()
            if not row:
                return None
            return dict(row)

    async def get_history(self, limit: int = 30) -> list[dict]:
        async with self._sf() as db:
            result = await db.execute(text("""
                SELECT ts, advances, declines, advance_decline_ratio, breadth_score
                FROM market_breadth_snapshots
                ORDER BY ts DESC LIMIT :lim
            """), {"lim": limit})
            return [dict(r) for r in result.mappings().fetchall()]

    async def _persist(self, snapshot: dict) -> None:
        import json
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO market_breadth_snapshots
                    (advances, declines, unchanged, new_highs_52w, new_lows_52w,
                     advance_decline_ratio, breadth_score, above_200dma_pct, sector_data)
                VALUES
                    (:adv, :dec, :unc, :new_highs, :new_lows, :ad_ratio,
                     :breadth_score, :above_200, :sector_data::jsonb)
            """), {
                "adv": snapshot["advances"],
                "dec": snapshot["declines"],
                "unc": snapshot["unchanged"],
                "new_highs": snapshot["new_highs_52w"],
                "new_lows": snapshot["new_lows_52w"],
                "ad_ratio": snapshot["advance_decline_ratio"],
                "breadth_score": snapshot["breadth_score"],
                "above_200": snapshot["above_200dma_pct"],
                "sector_data": json.dumps({}),
            })
            await db.commit()
