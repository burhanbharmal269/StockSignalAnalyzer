"""RegimeResolver — 8-rule priority matrix.

Takes a DirectionSignal + VolatilitySignal and returns
(primary_regime: MarketRegime, secondary_regime: MarketRegime | None).

Rules (ordered by priority, highest first):

 1. is_panic (VIX > 28)             → HIGH_VOLATILITY
 2. HIGH vola + ADX < trend_strong   → HIGH_VOLATILITY
 3. HIGH vola + ADX >= strong + BULL → TRENDING_BULLISH  (secondary: HIGH_VOLATILITY)
 4. HIGH vola + ADX >= strong + BEAR → TRENDING_BEARISH  (secondary: HIGH_VOLATILITY)
 5. LOW vola                         → LOW_VOLATILITY
 6. NORMAL vola + BULLISH gate open  → TRENDING_BULLISH
 7. NORMAL vola + BEARISH gate open  → TRENDING_BEARISH
 8. Fallthrough                      → SIDEWAYS
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime

if TYPE_CHECKING:
    from core.domain.regime.trend_layer import DirectionSignal
    from core.domain.regime.volatility_layer import VolatilitySignal
    from core.infrastructure.config.regime_config import RegimeConfig


class RegimeResolver:
    """Pure stateless 8-rule priority resolver."""

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config

    def resolve(
        self,
        direction: DirectionSignal,
        volatility: VolatilitySignal,
    ) -> tuple[MarketRegime, MarketRegime | None]:
        """Apply rules in priority order. Returns (primary, secondary | None)."""
        cfg = self._cfg

        # Rule 1: Panic override
        if volatility.is_panic:
            return MarketRegime.HIGH_VOLATILITY, None

        # Rules 2–4: Elevated volatility zone
        if volatility.level == "HIGH":
            if direction.adx_strength < cfg.adx.trend_strong or not direction.is_gate_open:
                # Rule 2: High vol + no trending confirmation
                return MarketRegime.HIGH_VOLATILITY, None

            # ADX is strong — regime is trending but with high-vol secondary
            if direction.direction == "BULLISH":
                # Rule 3
                return MarketRegime.TRENDING_BULLISH, MarketRegime.HIGH_VOLATILITY
            # Rule 4
            return MarketRegime.TRENDING_BEARISH, MarketRegime.HIGH_VOLATILITY

        # Rule 5: Low volatility
        if volatility.level == "LOW":
            return MarketRegime.LOW_VOLATILITY, None

        # Normal volatility — Rules 6, 7
        if direction.is_gate_open:
            if direction.direction == "BULLISH":
                # Rule 6
                return MarketRegime.TRENDING_BULLISH, None
            # Rule 7
            return MarketRegime.TRENDING_BEARISH, None

        # Rule 8: Fallthrough
        return MarketRegime.SIDEWAYS, None
