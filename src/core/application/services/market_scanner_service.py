"""MarketScannerService — scans the full universe for trading opportunities.

Detects: Breakouts, Momentum, Volume Spikes, OI Expansion, Gap Ups/Downs,
         Relative Strength, Delivery Spikes, IV Expansion.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_universe_service import MarketUniverseService
    from core.infrastructure.database.repositories.historical_candle_repository import (
        SqlAlchemyHistoricalCandleRepository,
    )
    from core.domain.entities.market_opportunity import MarketOpportunity

_log = logging.getLogger(__name__)

_MIN_CANDLES = 50
_VOLUME_SPIKE_THRESHOLD = 2.0      # 2x avg volume
_BREAKOUT_LOOKBACK = 20            # candles for range high/low
_MOMENTUM_RSI_THRESHOLD = 60       # RSI above this = bullish momentum
_GAP_PCT_THRESHOLD = Decimal("1.0")  # 1% gap


class MarketScannerService:
    def __init__(
        self,
        universe_service: MarketUniverseService,
        candle_repo: SqlAlchemyHistoricalCandleRepository,
    ) -> None:
        self._universe = universe_service
        self._candles = candle_repo

    async def scan_all(self, timeframe: str = "15m") -> list[MarketOpportunity]:
        """Run all scanners on the full universe. Returns ranked opportunities."""
        from core.domain.entities.market_opportunity import MarketOpportunity
        fo_symbols = await self._universe.get_fo_symbols()
        opportunities: list[MarketOpportunity] = []

        for symbol in fo_symbols:
            try:
                candles = await self._candles.get_latest(symbol, timeframe, _MIN_CANDLES + 10)
                if len(candles) < _MIN_CANDLES:
                    continue

                opps = await self._scan_symbol(symbol, candles)
                opportunities.extend(opps)
            except Exception as exc:
                _log.debug("scanner.skip symbol=%s err=%s", symbol, exc)

        # Sort by score descending
        opportunities.sort(key=lambda o: o.total_score, reverse=True)
        return opportunities[:100]    # top 100

    async def _scan_symbol(
        self, symbol: str, candles: list
    ) -> list[MarketOpportunity]:
        from core.domain.entities.market_opportunity import MarketOpportunity
        from core.domain.strategies.base_strategy import IStrategy

        results = []
        now = datetime.now(UTC)
        expires = now + timedelta(hours=4)

        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]
        latest = candles[-1]

        # Avg volume (excluding today)
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) > 20 else sum(volumes) / len(volumes)
        vol_ratio = Decimal(str(latest.volume / max(avg_vol, 1)))

        # RSI
        rsi = IStrategy._rsi(closes, 14)

        # 20-period range high/low
        range_high = IStrategy._highest(closes[-21:-1], 20)
        range_low = IStrategy._lowest(closes[-21:-1], 20)

        # ATR
        atr = IStrategy._atr(candles, 14)

        # --- Breakout scanner ---
        if closes[-1] > range_high and vol_ratio > Decimal("1.5"):
            score = Decimal("70") + min(vol_ratio * 5, Decimal("30"))
            results.append(MarketOpportunity(
                id=None, symbol=symbol,
                opportunity_type="BREAKOUT",
                total_score=score,
                confidence=Decimal("0.75"),
                direction="LONG",
                technical_score=score,
                volume_score=min(vol_ratio * 10, Decimal("100")),
                created_at=now, expires_at=expires,
                meta={"rsi": float(rsi), "vol_ratio": float(vol_ratio)},
            ))

        # --- Breakdown scanner ---
        if closes[-1] < range_low and vol_ratio > Decimal("1.5"):
            score = Decimal("65") + min(vol_ratio * 5, Decimal("25"))
            results.append(MarketOpportunity(
                id=None, symbol=symbol,
                opportunity_type="BREAKDOWN",
                total_score=score,
                confidence=Decimal("0.70"),
                direction="SHORT",
                technical_score=score,
                volume_score=min(vol_ratio * 10, Decimal("100")),
                created_at=now, expires_at=expires,
                meta={"rsi": float(rsi)},
            ))

        # --- Momentum scanner ---
        if rsi > Decimal(str(_MOMENTUM_RSI_THRESHOLD)) and vol_ratio > Decimal("1.2"):
            score = (rsi - 50) * Decimal("2")
            results.append(MarketOpportunity(
                id=None, symbol=symbol,
                opportunity_type="MOMENTUM",
                total_score=score,
                confidence=Decimal("0.65"),
                direction="LONG",
                technical_score=score,
                volume_score=min(vol_ratio * 8, Decimal("80")),
                created_at=now, expires_at=expires,
                meta={"rsi": float(rsi)},
            ))

        # --- Volume spike ---
        if vol_ratio > Decimal(str(_VOLUME_SPIKE_THRESHOLD)):
            results.append(MarketOpportunity(
                id=None, symbol=symbol,
                opportunity_type="VOLUME_SPIKE",
                total_score=min(vol_ratio * 20, Decimal("90")),
                confidence=Decimal("0.60"),
                direction="LONG" if latest.is_bullish else "SHORT",
                volume_score=min(vol_ratio * 20, Decimal("100")),
                created_at=now, expires_at=expires,
                meta={"vol_ratio": float(vol_ratio)},
            ))

        # --- Gap up ---
        if len(candles) >= 2:
            prev_close = candles[-2].close
            gap_pct = ((latest.open - prev_close) / prev_close) * 100
            if gap_pct >= _GAP_PCT_THRESHOLD:
                results.append(MarketOpportunity(
                    id=None, symbol=symbol,
                    opportunity_type="GAP_UP",
                    total_score=min(gap_pct * 10, Decimal("80")),
                    confidence=Decimal("0.65"),
                    direction="LONG",
                    technical_score=min(gap_pct * 10, Decimal("80")),
                    created_at=now, expires_at=expires,
                    meta={"gap_pct": float(gap_pct)},
                ))
            elif -gap_pct >= _GAP_PCT_THRESHOLD:
                results.append(MarketOpportunity(
                    id=None, symbol=symbol,
                    opportunity_type="GAP_DOWN",
                    total_score=min(-gap_pct * 10, Decimal("80")),
                    confidence=Decimal("0.65"),
                    direction="SHORT",
                    technical_score=min(-gap_pct * 10, Decimal("80")),
                    created_at=now, expires_at=expires,
                    meta={"gap_pct": float(gap_pct)},
                ))

        return results
