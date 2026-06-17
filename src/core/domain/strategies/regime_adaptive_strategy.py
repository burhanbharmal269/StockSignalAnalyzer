"""Regime Adaptive Strategy.

Detects market regime (trending/ranging/volatile) then delegates
to the best sub-strategy for that regime.

Regime detection:
- TRENDING_UP / TRENDING_DOWN: ADX > 25, price above/below 200 EMA
- RANGING: ADX < 20, price within Bollinger Band squeeze
- VOLATILE: ATR percentile > 80th (high ATR vs 30-period average)
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from core.domain.strategies.base_strategy import IStrategy, StrategySignal
from core.domain.strategies.ema_trend_strategy import EMATrendStrategy
from core.domain.strategies.momentum_strategy import MomentumStrategy
from core.domain.strategies.vwap_pullback_strategy import VWAPPullbackStrategy

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle

Regime = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE", "UNKNOWN"]

_ema_strategy = EMATrendStrategy()
_momentum_strategy = MomentumStrategy()
_vwap_strategy = VWAPPullbackStrategy()


class RegimeAdaptiveStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "REGIME_ADAPTIVE"

    @property
    def description(self) -> str:
        return "Auto-selects EMA/Momentum/VWAP sub-strategy based on detected market regime"

    @property
    def min_candles_required(self) -> int:
        return 220

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["15m", "60m", "D"]

    def detect_regime(self, candles: list[HistoricalCandle]) -> Regime:
        if len(candles) < 220:
            return "UNKNOWN"

        closes = [c.close for c in candles]

        ema200 = self._ema(closes, 200)
        ema50 = self._ema(closes, 50)
        if not ema200 or not ema50:
            return "UNKNOWN"

        price = closes[-1]
        cur_ema200 = ema200[-1]
        cur_ema50 = ema50[-1]

        # ADX approximation via DM
        adx = self._calculate_adx(candles, 14)

        # Current ATR vs 30-period ATR average
        atr_now = self._atr(candles[-15:], 14) if len(candles) >= 15 else Decimal("0")
        atr_avg = sum(
            self._atr(candles[-(i + 15):-(i) if i > 0 else len(candles)], 14)
            for i in range(1, 31) if len(candles) >= i + 15
        ) / 30 if len(candles) >= 45 else atr_now

        if atr_avg > 0 and atr_now / atr_avg > Decimal("1.8"):
            return "VOLATILE"

        if adx > Decimal("25"):
            return "TRENDING_UP" if price > cur_ema200 and cur_ema50 > cur_ema200 else "TRENDING_DOWN"

        if adx < Decimal("20"):
            return "RANGING"

        return "TRENDING_UP" if price > cur_ema200 else "TRENDING_DOWN"

    def _calculate_adx(self, candles: list[HistoricalCandle], period: int) -> Decimal:
        """Simplified ADX using EMA of absolute directional movement."""
        if len(candles) < period + 2:
            return Decimal("0")

        highs = [c.high for c in candles[-(period + 2):]]
        lows = [c.low for c in candles[-(period + 2):]]
        closes = [c.close for c in candles[-(period + 2):]]

        dm_pos = []
        dm_neg = []
        tr_list = []

        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            dm_pos.append(up_move if up_move > down_move and up_move > 0 else Decimal("0"))
            dm_neg.append(down_move if down_move > up_move and down_move > 0 else Decimal("0"))
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            tr_list.append(tr)

        if not tr_list:
            return Decimal("0")

        avg_tr = sum(tr_list) / len(tr_list)
        avg_pos = sum(dm_pos) / len(dm_pos)
        avg_neg = sum(dm_neg) / len(dm_neg)

        if avg_tr == 0:
            return Decimal("0")

        di_pos = (avg_pos / avg_tr) * 100
        di_neg = (avg_neg / avg_tr) * 100
        di_sum = di_pos + di_neg
        if di_sum == 0:
            return Decimal("0")

        dx = abs(di_pos - di_neg) / di_sum * 100
        return dx

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        regime = self.detect_regime(candles)

        if regime in ("TRENDING_UP", "TRENDING_DOWN"):
            signal = await _ema_strategy.generate_signal(symbol, candles, params)
            if signal is None:
                signal = await _momentum_strategy.generate_signal(symbol, candles, params)
        elif regime == "RANGING":
            signal = await _vwap_strategy.generate_signal(symbol, candles, params)
        elif regime == "VOLATILE":
            # Tighter stops, lower confidence in volatile regime
            signal = await _momentum_strategy.generate_signal(symbol, candles, params)
            if signal:
                signal = StrategySignal(
                    **{**signal.__dict__,
                       "confidence": signal.confidence * Decimal("0.8"),
                       "risk_score": min(signal.risk_score * Decimal("1.3"), Decimal("1")),
                       "meta": {**signal.meta, "regime": regime}}
                )
        else:
            return None

        if signal:
            signal.strategy_name = self.name
            if "regime" not in (signal.meta or {}):
                signal.meta["regime"] = regime

        return signal
