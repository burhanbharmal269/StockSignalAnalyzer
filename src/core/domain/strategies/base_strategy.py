"""IStrategy — pluggable strategy interface for signal generation.

Every concrete strategy must implement generate_signal().
The result feeds into the existing Risk Engine — strategies never place
orders directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


@dataclass
class StrategySignal:
    """Output from a strategy — candidate for the Risk Engine."""
    symbol: str
    strategy_name: str
    direction: str          # LONG | SHORT
    confidence: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    target: Decimal
    risk_score: Decimal     # 0-1, higher = riskier
    timeframe: str
    meta: dict = field(default_factory=dict)


class IStrategy(ABC):
    """Base class for all trading strategies.

    Strategies are stateless — all state lives in the candle window
    passed to generate_signal().
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def min_candles_required(self) -> int:
        return 50

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["15m", "60m"]

    @abstractmethod
    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None: ...

    # ------------------------------------------------------------------
    # Shared technical helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ema(values: list[Decimal], period: int) -> list[Decimal]:
        if not values or period <= 0:
            return []
        k = Decimal(2) / (period + 1)
        result = [values[0]]
        for v in values[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    @staticmethod
    def _sma(values: list[Decimal], period: int) -> list[Decimal]:
        result = []
        for i in range(len(values)):
            if i < period - 1:
                result.append(Decimal(0))
            else:
                result.append(sum(values[i - period + 1: i + 1]) / period)
        return result

    @staticmethod
    def _atr(candles: list[HistoricalCandle], period: int = 14) -> Decimal:
        if len(candles) < 2:
            return Decimal(0)
        trs = []
        for i in range(1, len(candles)):
            prev_close = candles[i - 1].close
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - prev_close),
                abs(candles[i].low - prev_close),
            )
            trs.append(tr)
        window = trs[-period:] if len(trs) >= period else trs
        return sum(window) / len(window) if window else Decimal(0)

    @staticmethod
    def _highest(values: list[Decimal], period: int) -> Decimal:
        window = values[-period:] if len(values) >= period else values
        return max(window) if window else Decimal(0)

    @staticmethod
    def _lowest(values: list[Decimal], period: int) -> Decimal:
        window = values[-period:] if len(values) >= period else values
        return min(window) if window else Decimal(0)

    @staticmethod
    def _vwap(candles: list[HistoricalCandle]) -> list[Decimal]:
        """Cumulative VWAP from session start — returns one value per candle."""
        result = []
        cum_pv = Decimal(0)
        cum_vol = Decimal(0)
        for c in candles:
            cum_pv += c.typical_price * c.volume
            cum_vol += c.volume
            result.append(cum_pv / cum_vol if cum_vol > 0 else c.close)
        return result

    @staticmethod
    def _rsi(closes: list[Decimal], period: int = 14) -> Decimal:
        if len(closes) < period + 1:
            return Decimal(50)
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, Decimal(0)))
            losses.append(max(-diff, Decimal(0)))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return Decimal(100)
        rs = avg_gain / avg_loss
        return Decimal(100) - (Decimal(100) / (1 + rs))
