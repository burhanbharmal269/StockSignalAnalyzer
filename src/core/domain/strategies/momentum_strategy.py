"""Momentum Strategy.

Combines RSI, rate-of-change (ROC), and relative strength vs index.
Entry: High RSI + strong ROC + above 20 EMA (long) or vice versa (short).
Trailing stop based on ATR.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.strategies.base_strategy import IStrategy, StrategySignal

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class MomentumStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "MOMENTUM"

    @property
    def description(self) -> str:
        return "RSI + ROC momentum with EMA filter"

    @property
    def min_candles_required(self) -> int:
        return 30

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["15m", "60m"]

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        p = params or {}
        rsi_period = int(p.get("rsi_period", 14))
        roc_period = int(p.get("roc_period", 10))
        ema_period = int(p.get("ema_period", 20))
        rsi_bull_threshold = Decimal(str(p.get("rsi_bull", 60)))
        rsi_bear_threshold = Decimal(str(p.get("rsi_bear", 40)))

        if len(candles) < max(rsi_period, roc_period, ema_period) + 5:
            return None

        closes = [c.close for c in candles]
        rsi = self._rsi(closes, rsi_period)
        ema = self._ema(closes, ema_period)
        atr = self._atr(candles, 14)

        if not ema or atr == 0:
            return None

        price = closes[-1]
        cur_ema = ema[-1]

        # Rate of Change
        if len(closes) > roc_period:
            roc = ((price - closes[-roc_period - 1]) / closes[-roc_period - 1]) * 100
        else:
            return None

        # Volume strength
        volumes = [c.volume for c in candles]
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) > 20 else sum(volumes) / len(volumes)
        vol_ratio = volumes[-1] / max(avg_vol, Decimal("1"))

        # Bullish momentum
        if (rsi > rsi_bull_threshold
                and roc > Decimal("1")
                and price > cur_ema
                and vol_ratio > Decimal("1.1")):
            confidence = min(
                Decimal("0.60")
                + (rsi - rsi_bull_threshold) / 100
                + min(roc / 50, Decimal("0.15")),
                Decimal("0.85"),
            )
            stop = price - atr * Decimal("2")
            target = price + atr * Decimal("4")
            risk = (price - stop) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="LONG",
                confidence=confidence,
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"rsi": float(rsi), "roc": float(roc), "vol_ratio": float(vol_ratio)},
            )

        # Bearish momentum
        if (rsi < rsi_bear_threshold
                and roc < Decimal("-1")
                and price < cur_ema
                and vol_ratio > Decimal("1.1")):
            confidence = min(
                Decimal("0.58")
                + (rsi_bear_threshold - rsi) / 100
                + min(-roc / 50, Decimal("0.12")),
                Decimal("0.80"),
            )
            stop = price + atr * Decimal("2")
            target = price - atr * Decimal("4")
            risk = (stop - price) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="SHORT",
                confidence=confidence,
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={"rsi": float(rsi), "roc": float(roc)},
            )

        return None
