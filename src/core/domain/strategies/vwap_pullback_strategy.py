"""VWAP Pullback Strategy.

Entry: Price pulls back to VWAP in an uptrend (price was > VWAP), RSI 35-58, volume below avg.
       Or bounces down from VWAP in downtrend.
Stop:  5-bar swing low/high +/- 0.2x ATR.
Target: 2:1 R/R.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.strategies.base_strategy import IStrategy, StrategySignal

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class VWAPPullbackStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "VWAP_PULLBACK"

    @property
    def description(self) -> str:
        return "VWAP pullback entries in established intraday trends"

    @property
    def min_candles_required(self) -> int:
        return 30

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["5m", "15m"]

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        if len(candles) < self.min_candles_required:
            return None

        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]

        vwap_series = self._vwap(candles)    # one value per candle
        vwap = vwap_series[-1]
        price = closes[-1]

        rsi = self._rsi(closes, 14)
        atr = self._atr(candles, 14)
        if atr == 0:
            return None

        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) > 20 else sum(volumes) / len(volumes)
        cur_vol = volumes[-1]

        # Require quieter volume (pullback, not reversal)
        if cur_vol > avg_vol * Decimal("1.2"):
            return None

        tolerance = atr * Decimal("0.35")

        # Count recent candles above/below VWAP (last 6, excluding current)
        lookback = min(6, len(candles) - 1)
        recent_closes = closes[-(lookback + 1):-1]
        recent_vwap = vwap_series[-(lookback + 1):-1]
        above_count = sum(1 for c, v in zip(recent_closes, recent_vwap) if c > v)
        below_count = lookback - above_count

        # Bullish pullback: mostly above VWAP, now at VWAP
        if (above_count >= lookback // 2 + 1
                and abs(price - vwap) <= tolerance
                and Decimal("35") <= rsi <= Decimal("58")):
            stop = self._lowest([c.low for c in candles[-5:]], 5) - atr * Decimal("0.2")
            target = price + (price - stop) * Decimal("2")
            risk = (price - stop) / price if price > stop else Decimal("0.05")
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="LONG",
                confidence=Decimal("0.68"),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"vwap": float(vwap), "rsi": float(rsi), "above_count": above_count},
            )

        # Bearish rejection: mostly below VWAP, price rallied to VWAP
        if (below_count >= lookback // 2 + 1
                and abs(price - vwap) <= tolerance
                and Decimal("42") <= rsi <= Decimal("65")):
            stop = self._highest([c.high for c in candles[-5:]], 5) + atr * Decimal("0.2")
            target = price - (stop - price) * Decimal("2")
            risk = (stop - price) / price if stop > price else Decimal("0.05")
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="SHORT",
                confidence=Decimal("0.62"),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"vwap": float(vwap), "rsi": float(rsi), "below_count": below_count},
            )

        return None
