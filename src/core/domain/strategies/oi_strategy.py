"""OI (Open Interest) Based Strategy.

Reads option chain data to determine:
- High PCR + price at support → bullish (market sold puts, expect reversal up)
- Low PCR + price at resistance → bearish
- Max Pain: price drift toward max pain level
- OI unwinding: signal exhaustion of current move
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.strategies.base_strategy import IStrategy, StrategySignal

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class OIStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "OI_STRATEGY"

    @property
    def description(self) -> str:
        return "Option OI-based signals using PCR and Max Pain"

    @property
    def min_candles_required(self) -> int:
        return 20

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["15m", "60m"]

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        """Params must include: pcr, max_pain, oi_pattern (from option_chain_service)."""
        p = params or {}
        pcr = Decimal(str(p.get("pcr", 1.0)))
        max_pain = Decimal(str(p.get("max_pain", 0)))
        oi_pattern = p.get("oi_pattern", "NEUTRAL")

        if len(candles) < self.min_candles_required:
            return None

        closes = [c.close for c in candles]
        price = closes[-1]
        atr = self._atr(candles, 14)

        if atr == 0 or max_pain == 0:
            return None

        # Max Pain drift: price tends toward max pain into expiry
        distance_to_max_pain = (max_pain - price) / price * 100
        max_pain_signal = None

        if distance_to_max_pain > Decimal("1.5"):   # price well below max pain → bullish drift
            max_pain_signal = "LONG"
        elif distance_to_max_pain < Decimal("-1.5"):  # price above max pain → bearish drift
            max_pain_signal = "SHORT"

        # PCR-based signal
        pcr_signal = None
        if pcr > Decimal("1.3"):     # excess put OI → contrarian bullish
            pcr_signal = "LONG"
        elif pcr < Decimal("0.7"):   # excess call OI → contrarian bearish
            pcr_signal = "SHORT"

        # OI pattern confirmation
        pattern_signal = None
        if oi_pattern == "SHORT_COVERING":
            pattern_signal = "LONG"
        elif oi_pattern == "LONG_BUILDUP":
            pattern_signal = "LONG"
        elif oi_pattern == "SHORT_BUILDUP":
            pattern_signal = "SHORT"
        elif oi_pattern == "LONG_UNWINDING":
            pattern_signal = "SHORT"

        # Need at least 2 confirming signals
        signals = [s for s in [max_pain_signal, pcr_signal, pattern_signal] if s is not None]
        if not signals:
            return None

        long_votes = signals.count("LONG")
        short_votes = signals.count("SHORT")
        total_votes = len(signals)

        if long_votes >= 2:
            confidence = Decimal("0.55") + Decimal(str(long_votes / total_votes)) * Decimal("0.25")
            stop = price - atr * Decimal("2")
            target = price + (price - stop) * Decimal("2")
            risk = (price - stop) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="LONG",
                confidence=min(confidence, Decimal("0.80")),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={
                    "pcr": float(pcr),
                    "max_pain": float(max_pain),
                    "oi_pattern": oi_pattern,
                    "votes": f"{long_votes}/{total_votes}",
                },
            )

        if short_votes >= 2:
            confidence = Decimal("0.52") + Decimal(str(short_votes / total_votes)) * Decimal("0.22")
            stop = price + atr * Decimal("2")
            target = price - (stop - price) * Decimal("2")
            risk = (stop - price) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="SHORT",
                confidence=min(confidence, Decimal("0.77")),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=candles[-1].timeframe,
                meta={
                    "pcr": float(pcr),
                    "max_pain": float(max_pain),
                    "oi_pattern": oi_pattern,
                    "votes": f"{short_votes}/{total_votes}",
                },
            )

        return None
