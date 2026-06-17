"""Opening Range Breakout (ORB) Strategy.

Uses the first N candles of the session as the range.
Entry: Close above range high (long) or below range low (short).
Requires volume confirmation.
Valid only during market hours (09:15-14:00 IST).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.strategies.base_strategy import IStrategy, StrategySignal

if TYPE_CHECKING:
    from core.domain.entities.historical_candle import HistoricalCandle


class ORBStrategy(IStrategy):
    @property
    def name(self) -> str:
        return "ORB"

    @property
    def description(self) -> str:
        return "Opening Range Breakout — first 30-min range with volume confirmation"

    @property
    def min_candles_required(self) -> int:
        return 10

    @property
    def preferred_timeframes(self) -> list[str]:
        return ["5m", "15m"]

    async def generate_signal(
        self,
        symbol: str,
        candles: list[HistoricalCandle],
        params: dict | None = None,
    ) -> StrategySignal | None:
        p = params or {}
        orb_candles_count = int(p.get("orb_candles", 6))   # 6 x 5m = 30 min range

        if len(candles) < orb_candles_count + 2:
            return None

        # Opening range: first N candles
        orb = candles[-len(candles):][:orb_candles_count]
        orb_high = max(c.high for c in orb)
        orb_low = min(c.low for c in orb)
        orb_range = orb_high - orb_low

        if orb_range == 0:
            return None

        current = candles[-1]
        volumes = [c.volume for c in candles]
        avg_vol = sum(volumes[orb_candles_count:-1]) / max(len(volumes) - orb_candles_count - 1, 1)

        atr = self._atr(candles, 14)
        if atr == 0:
            return None

        # Need a breakout candle with 1.3x avg volume
        vol_ok = current.volume > avg_vol * Decimal("1.3")
        price = current.close

        # Long breakout
        if price > orb_high and vol_ok:
            stop = orb_high - orb_range * Decimal("0.5")
            stop = max(stop, price - atr * Decimal("2"))
            target = price + orb_range * Decimal("2")
            risk = (price - stop) / price
            confidence = Decimal("0.72") + min(
                (current.volume / max(avg_vol, Decimal("1")) - 1) * Decimal("0.05"),
                Decimal("0.10")
            )
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="LONG",
                confidence=min(confidence, Decimal("0.85")),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=current.timeframe,
                meta={"orb_high": float(orb_high), "orb_low": float(orb_low), "orb_range": float(orb_range)},
            )

        # Short breakdown
        if price < orb_low and vol_ok:
            stop = orb_low + orb_range * Decimal("0.5")
            stop = min(stop, price + atr * Decimal("2"))
            target = price - orb_range * Decimal("2")
            risk = (stop - price) / price
            return StrategySignal(
                symbol=symbol,
                strategy_name=self.name,
                direction="SHORT",
                confidence=Decimal("0.68"),
                entry_price=price,
                stop_loss=stop,
                target=target,
                risk_score=min(risk * 2, Decimal("1")),
                timeframe=current.timeframe,
                meta={"orb_high": float(orb_high), "orb_low": float(orb_low)},
            )

        return None
