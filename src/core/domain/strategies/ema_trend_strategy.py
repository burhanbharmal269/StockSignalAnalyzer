"""EMA Trend Following Strategy.

Entry: Price crosses above EMA20 while EMA20 > EMA50 > EMA200 (bullish).
       Or below EMA20 while EMA20 < EMA50 < EMA200 (bearish).
Stop:  ATR-based (1.5x ATR).
Target: 3:1 Risk/Reward.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.strategies.base_strategy import IStrategy, StrategySignal

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class EMATrendStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "EMA_TREND"

    @property
    def description(self) -> str:
        return "EMA 20/50/200 trend following with ATR-based stops"

    @property
    def min_candles_required(self) -> int:
        return 210

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["15m", "60m", "D"]

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        p = params or {}
        fast = int(p.get("fast", 20))
        mid = int(p.get("mid", 50))
        slow = int(p.get("slow", 200))

        if len(candles) < slow + 5:
            return None

        closes = [c.close for c in candles]
        ema_fast = self._ema(closes, fast)
        ema_mid = self._ema(closes, mid)
        ema_slow = self._ema(closes, slow)

        if not (ema_fast and ema_mid and ema_slow):
            return None

        cur_fast = ema_fast[-1]
        cur_mid = ema_mid[-1]
        cur_slow = ema_slow[-1]
        prev_fast = ema_fast[-2]
        price = closes[-1]

        atr = self._atr(candles, 14)
        if atr == 0:
            return None

        # Bullish alignment
        if (cur_fast > cur_mid > cur_slow
                and price > cur_fast
                and prev_fast <= closes[-2]):
            stop = price - atr * Decimal("1.5")
            target = price + (price - stop) * Decimal("3")
            risk = (price - stop) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="LONG",
                confidence=Decimal("0.70"),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"ema20": float(cur_fast), "ema50": float(cur_mid)},
            )

        # Bearish alignment
        if (cur_fast < cur_mid < cur_slow
                and price < cur_fast
                and prev_fast >= closes[-2]):
            stop = price + atr * Decimal("1.5")
            target = price - (stop - price) * Decimal("3")
            risk = (stop - price) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="SHORT",
                confidence=Decimal("0.65"),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"ema20": float(cur_fast), "ema50": float(cur_mid)},
            )

        return None
