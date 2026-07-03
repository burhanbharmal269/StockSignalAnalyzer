"""MarketBreadthService — advance/decline ratio, 52W highs/lows, sector strength."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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


def _ema(closes: list[float], period: int) -> float:
    """Exponential moving average of the last `period` values (Wilder/EMA standard)."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    k = 2.0 / (period + 1)
    result = sum(closes[:period]) / period
    for price in closes[period:]:
        result = price * k + result * (1 - k)
    return result


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
        """Calculate current market breadth and persist snapshot. Phase 22 §7 enhanced."""
        symbols = await self._universe.get_active(segment="EQ", fo_only=True)
        sym_list = [s.symbol for s in symbols]
        # Build sector map for sector strength breakdown
        sector_map: dict[str, str] = {s.symbol: (s.sector or "Unknown") for s in symbols}

        advances = declines = unchanged = 0
        new_highs = new_lows = 0
        above_200 = above_50 = above_20 = above_vwap = 0
        sector_counters: dict[str, dict[str, int]] = {}

        for sym in sym_list[:200]:    # cap for performance
            sector = sector_map.get(sym, "Unknown")
            if sector not in sector_counters:
                sector_counters[sector] = {"advances": 0, "declines": 0, "total": 0}

            try:
                # Get daily candles for advance/decline + EMA/DMA checks
                daily = await self._candles.get_latest(sym, "D", limit=250)
                if len(daily) < 2:
                    continue

                closes = [float(c.close) for c in daily]
                last_close = closes[-1]
                prev_close = closes[-2]

                if last_close > prev_close:
                    advances += 1
                    sector_counters[sector]["advances"] += 1
                elif last_close < prev_close:
                    declines += 1
                    sector_counters[sector]["declines"] += 1
                else:
                    unchanged += 1
                sector_counters[sector]["total"] += 1

                # 52-week high/low
                if len(daily) >= 250:
                    year_high = max(c.high for c in daily[-250:])
                    year_low  = min(c.low  for c in daily[-250:])
                    if last_close >= year_high:
                        new_highs += 1
                    elif last_close <= year_low:
                        new_lows += 1

                # 200 DMA
                if len(daily) >= 200:
                    dma200 = sum(closes[-200:]) / 200
                    if last_close > dma200:
                        above_200 += 1

                # 50 EMA (Phase 22 §7)
                if len(daily) >= 50:
                    ema50 = _ema(closes, 50)
                    if last_close > ema50:
                        above_50 += 1

                # 20 EMA (Phase 22 §7)
                if len(daily) >= 20:
                    ema20 = _ema(closes, 20)
                    if last_close > ema20:
                        above_20 += 1

                # VWAP proxy: daily VWAP ≈ (H+L+C)/3 vs close (Phase 22 §7)
                # Using intraday VWAP approximation from candles with volume
                try:
                    intra = await self._candles.get_latest(sym, "15m", limit=30)
                    if intra and len(intra) >= 3:
                        tp_vols = [
                            (float(c.high) + float(c.low) + float(c.close)) / 3 * float(c.volume or 0)
                            for c in intra
                        ]
                        total_vol = sum(float(c.volume or 0) for c in intra)
                        if total_vol > 0:
                            vwap_val = sum(tp_vols) / total_vol
                            if last_close > vwap_val:
                                above_vwap += 1
                except Exception:
                    pass

            except Exception:
                pass

        tracked = len(sym_list[:200]) or 1
        total   = advances + declines + unchanged or 1
        ad_ratio      = advances / max(declines, 1)
        breadth_score = ((advances - declines) / total) * 100
        above_200_pct = above_200 / tracked * 100
        above_50_pct  = above_50  / tracked * 100
        above_20_pct  = above_20  / tracked * 100
        above_vwap_pct = above_vwap / tracked * 100

        # Sector strength: net-advance ratio per sector
        sector_strength: dict[str, Any] = {}
        for sec, cnt in sector_counters.items():
            if cnt["total"] > 0:
                net = (cnt["advances"] - cnt["declines"]) / cnt["total"] * 100
                sector_strength[sec] = {
                    "advances": cnt["advances"],
                    "declines": cnt["declines"],
                    "total": cnt["total"],
                    "net_pct": round(net, 1),
                }

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
            "above_50ema_pct":  round(above_50_pct, 2),
            "above_20ema_pct":  round(above_20_pct, 2),
            "above_vwap_pct":   round(above_vwap_pct, 2),
            "sector_strength": sector_strength,
            "total_tracked": tracked,
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
        # Store new EMA/VWAP/sector fields inside sector_data JSONB column
        extra = {
            "above_50ema_pct":  snapshot.get("above_50ema_pct", 0.0),
            "above_20ema_pct":  snapshot.get("above_20ema_pct", 0.0),
            "above_vwap_pct":   snapshot.get("above_vwap_pct", 0.0),
            "sector_strength":  snapshot.get("sector_strength", {}),
        }
        async with self._sf() as db:
            await db.execute(text("""
                INSERT INTO market_breadth_snapshots
                    (advances, declines, unchanged, new_highs_52w, new_lows_52w,
                     advance_decline_ratio, breadth_score, above_200dma_pct, sector_data)
                VALUES
                    (:adv, :dec, :unc, :new_highs, :new_lows, :ad_ratio,
                     :breadth_score, :above_200, CAST(:sector_data AS jsonb))
            """), {
                "adv": snapshot["advances"],
                "dec": snapshot["declines"],
                "unc": snapshot["unchanged"],
                "new_highs": snapshot["new_highs_52w"],
                "new_lows": snapshot["new_lows_52w"],
                "ad_ratio": snapshot["advance_decline_ratio"],
                "breadth_score": snapshot["breadth_score"],
                "above_200": snapshot["above_200dma_pct"],
                "sector_data": json.dumps(extra),
            })
            await db.commit()
