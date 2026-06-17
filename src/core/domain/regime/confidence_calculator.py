"""ConfidenceCalculator — per-regime scoring tables from Doc 20.

All thresholds come from RegimeConfig (config/regime.yaml).
Returns an integer 0–100 confidence score for each regime classification.

Scoring philosophy:
 - Start with a base score specific to each regime.
 - Add points for confirming indicators.
 - Apply hard-gate penalties (cap at 30) when key conditions are absent.
 - Clamp final result to [0, 100].
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime

if TYPE_CHECKING:
    from core.domain.regime.trend_layer import DirectionSignal
    from core.domain.regime.volatility_layer import VolatilitySignal
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot
    from core.infrastructure.config.regime_config import RegimeConfig


class ConfidenceCalculator:
    """Per-regime scoring tables. Pure, stateless."""

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config

    def calculate(
        self,
        regime: MarketRegime,
        direction: DirectionSignal,
        volatility: VolatilitySignal,
        snapshot: FeatureSnapshot,
    ) -> tuple[int, float, list[str]]:
        """Return (confidence: int, raw_score: float, explanation: list[str]).

        confidence is the integer 0–100 result used by the smoother.
        raw_score is the un-clamped weighted sum (useful for debugging).
        explanation lists the factors that contributed positively or negatively.
        """
        if regime in (MarketRegime.TRENDING_BULLISH, MarketRegime.TRENDING_BEARISH):
            return self._score_trending(regime, direction, snapshot)
        if regime == MarketRegime.SIDEWAYS:
            return self._score_sideways(direction, volatility, snapshot)
        if regime == MarketRegime.HIGH_VOLATILITY:
            return self._score_high_volatility(volatility, snapshot)
        return self._score_low_volatility(volatility, snapshot)

    # ------------------------------------------------------------------
    # Per-regime scoring methods
    # ------------------------------------------------------------------

    def _score_trending(
        self,
        regime: MarketRegime,
        direction: DirectionSignal,
        snapshot: FeatureSnapshot,
    ) -> tuple[int, float, list[str]]:
        cfg = self._cfg
        score = 0.0
        hard_gate_hit = False
        reasons: list[str] = []

        # Base: ADX strength
        if direction.adx_strength >= cfg.adx.trend_strong:
            score += 35.0
            reasons.append(f"ADX={direction.adx_strength:.1f} >= {cfg.adx.trend_strong}")
        elif direction.adx_strength >= cfg.adx.trend_weak:
            score += 20.0
            reasons.append(f"ADX={direction.adx_strength:.1f} (weak trend zone)")
        else:
            hard_gate_hit = True
            reasons.append(f"HARD_GATE: ADX={direction.adx_strength:.1f} < {cfg.adx.trend_weak}")

        # DI spread
        if direction.di_spread >= cfg.di_spread.strong:
            score += 15.0
            reasons.append(
                f"DI_spread={direction.di_spread:.1f} >= {cfg.di_spread.strong} (strong)"
            )
        elif direction.di_spread >= cfg.di_spread.hard_gate_min:
            score += 8.0
            reasons.append(f"DI_spread={direction.di_spread:.1f} (moderate)")
        else:
            hard_gate_hit = True
            reasons.append(
                f"HARD_GATE: DI_spread={direction.di_spread:.1f}"
                f" < {cfg.di_spread.hard_gate_min}"
            )

        # EMA alignment (price above/below 200 EMA in line with direction)
        if snapshot.close_price is not None and snapshot.ema_200 is not None:
            bullish = regime == MarketRegime.TRENDING_BULLISH
            if bullish and snapshot.close_price > snapshot.ema_200:
                score += 10.0
                reasons.append("price > EMA200 (bullish alignment)")
            elif not bullish and snapshot.close_price < snapshot.ema_200:
                score += 10.0
                reasons.append("price < EMA200 (bearish alignment)")

        # EMA stack: 20 > 50 > 200 (bullish) or 20 < 50 < 200 (bearish)
        if (
            snapshot.ema_20 is not None
            and snapshot.ema_50 is not None
            and snapshot.ema_200 is not None
        ):
            bullish = regime == MarketRegime.TRENDING_BULLISH
            stack_ok = (
                (snapshot.ema_20 > snapshot.ema_50 > snapshot.ema_200)
                if bullish
                else (snapshot.ema_20 < snapshot.ema_50 < snapshot.ema_200)
            )
            if stack_ok:
                score += 10.0
                reasons.append("EMA stack aligned")

        # Supertrend direction confirmation
        if snapshot.supertrend_direction is not None:
            bullish = regime == MarketRegime.TRENDING_BULLISH
            if (bullish and snapshot.supertrend_direction == 1) or (
                not bullish and snapshot.supertrend_direction == -1
            ):
                score += 10.0
                reasons.append(f"supertrend={snapshot.supertrend_direction} confirms direction")

        # Breadth: nifty above 200 DMA
        if snapshot.nifty_above_200dma_pct is not None:
            pct = snapshot.nifty_above_200dma_pct
            bullish = regime == MarketRegime.TRENDING_BULLISH
            if bullish and pct >= cfg.nifty_above_200dma.bull_strong:
                score += 5.0
                reasons.append(f"breadth={pct:.0f}% above 200DMA (strong bull)")
            elif bullish and pct >= cfg.nifty_above_200dma.bull:
                score += 3.0
                reasons.append(f"breadth={pct:.0f}% above 200DMA (bull)")

        # FII conviction
        if snapshot.fii_net_buying_days is not None:
            days = abs(snapshot.fii_net_buying_days)
            bullish = regime == MarketRegime.TRENDING_BULLISH
            fii_aligns = (
                (bullish and snapshot.fii_net_buying_days > 0)
                or (not bullish and snapshot.fii_net_buying_days < 0)
            )
            if fii_aligns and days >= cfg.fii_consecutive_days:
                score += 5.0
                reasons.append(f"FII {days} consecutive days aligned")

        # VIX must not be elevated for clean trending
        if snapshot.india_vix is not None and snapshot.india_vix > cfg.vix.elevated:
            score -= 10.0
            reasons.append(f"VIX={snapshot.india_vix:.1f} > {cfg.vix.elevated} (elevated, penalty)")

        if hard_gate_hit:
            raw = score
            score = min(score, 30.0)
            reasons.append(f"hard_gate capped: {raw:.1f} → {score:.1f}")

        return self._finalise(score, reasons)

    def _score_sideways(
        self,
        direction: DirectionSignal,
        volatility: VolatilitySignal,
        snapshot: FeatureSnapshot,
    ) -> tuple[int, float, list[str]]:
        cfg = self._cfg
        score = 0.0
        reasons: list[str] = []

        # ADX must be weak for SIDEWAYS
        if direction.adx_strength < cfg.adx.sideways:
            score += 35.0
            reasons.append(f"ADX={direction.adx_strength:.1f} < {cfg.adx.sideways} (non-trending)")
        elif direction.adx_strength < cfg.adx.trend_weak:
            score += 20.0
            reasons.append(f"ADX={direction.adx_strength:.1f} in weak zone")
        else:
            score = min(score, 30.0)
            reasons.append(f"HARD_GATE: ADX={direction.adx_strength:.1f} >= {cfg.adx.trend_weak}")

        # BB Width compression
        if snapshot.bb_width_percentile is not None:
            bwp = snapshot.bb_width_percentile
            if bwp < cfg.bb_width_percentile.very_low:
                score += 15.0
                reasons.append(
                    f"BB_width_pct={bwp:.0f} < {cfg.bb_width_percentile.very_low}"
                    " (strong squeeze)"
                )
            elif bwp < cfg.bb_width_percentile.low:
                score += 8.0
                reasons.append(f"BB_width_pct={bwp:.0f} < {cfg.bb_width_percentile.low} (squeeze)")

        # PCR neutral
        if snapshot.pcr is not None:
            if cfg.pcr.neutral_lower <= snapshot.pcr <= cfg.pcr.neutral_upper:
                score += 10.0
                reasons.append(f"PCR={snapshot.pcr:.2f} in neutral range")

        # ATR ratio low
        if snapshot.atr_ratio is not None:
            if snapshot.atr_ratio < cfg.atr_ratio.low:
                score += 10.0
                reasons.append(
                    f"ATR_ratio={snapshot.atr_ratio:.2f} < {cfg.atr_ratio.low} (low vol)"
                )

        # Low VIX
        if volatility.vix_value > 0 and volatility.vix_value < cfg.vix.low:
            score += 10.0
            reasons.append(f"VIX={volatility.vix_value:.1f} < {cfg.vix.low} (calm market)")

        return self._finalise(score, reasons)

    def _score_high_volatility(
        self,
        volatility: VolatilitySignal,
        snapshot: FeatureSnapshot,
    ) -> tuple[int, float, list[str]]:
        cfg = self._cfg
        score = 0.0
        reasons: list[str] = []

        if volatility.is_panic:
            score += 50.0
            reasons.append(f"VIX={volatility.vix_value:.1f} > {cfg.vix.panic} (PANIC)")
        elif volatility.vix_value > cfg.vix.high:
            score += 35.0
            reasons.append(f"VIX={volatility.vix_value:.1f} > {cfg.vix.high}")

        if volatility.atr_ratio_value > cfg.atr_ratio.very_high:
            score += 15.0
            reasons.append(
                f"ATR_ratio={volatility.atr_ratio_value:.2f}"
                f" > {cfg.atr_ratio.very_high} (extreme)"
            )
        elif volatility.atr_ratio_value > cfg.atr_ratio.high:
            score += 10.0
            reasons.append(f"ATR_ratio={volatility.atr_ratio_value:.2f} > {cfg.atr_ratio.high}")

        if snapshot.iv_percentile is not None:
            ivp = snapshot.iv_percentile
            if ivp >= cfg.iv_percentile.extreme:
                score += 15.0
                reasons.append(f"IV_pct={ivp:.0f} >= {cfg.iv_percentile.extreme} (extreme)")
            elif ivp >= cfg.iv_percentile.very_high:
                score += 10.0
                reasons.append(f"IV_pct={ivp:.0f} >= {cfg.iv_percentile.very_high}")
            elif ivp >= cfg.iv_percentile.high:
                score += 5.0
                reasons.append(f"IV_pct={ivp:.0f} >= {cfg.iv_percentile.high}")

        if snapshot.advance_decline_ratio is not None:
            adr = snapshot.advance_decline_ratio
            if adr > cfg.advance_decline.panic_high or adr < cfg.advance_decline.panic_low:
                score += 10.0
                reasons.append(f"A/D={adr:.2f} in panic range")

        return self._finalise(score, reasons)

    def _score_low_volatility(
        self,
        volatility: VolatilitySignal,
        snapshot: FeatureSnapshot,
    ) -> tuple[int, float, list[str]]:
        cfg = self._cfg
        score = 0.0
        reasons: list[str] = []

        if volatility.vix_value > 0 and volatility.vix_value < cfg.vix.very_low:
            score += 40.0
            reasons.append(f"VIX={volatility.vix_value:.1f} < {cfg.vix.very_low} (very low)")
        elif volatility.vix_value > 0 and volatility.vix_value < cfg.vix.low:
            score += 25.0
            reasons.append(f"VIX={volatility.vix_value:.1f} < {cfg.vix.low} (low)")

        if volatility.atr_ratio_value > 0 and volatility.atr_ratio_value < cfg.atr_ratio.very_low:
            score += 20.0
            reasons.append(f"ATR_ratio={volatility.atr_ratio_value:.2f} < {cfg.atr_ratio.very_low}")
        elif volatility.atr_ratio_value > 0 and volatility.atr_ratio_value < cfg.atr_ratio.low:
            score += 10.0
            reasons.append(f"ATR_ratio={volatility.atr_ratio_value:.2f} < {cfg.atr_ratio.low}")

        if snapshot.bb_width_percentile is not None:
            bwp = snapshot.bb_width_percentile
            if bwp < cfg.bb_width_percentile.extreme_low:
                score += 20.0
                reasons.append(
                    f"BB_width_pct={bwp:.0f} < {cfg.bb_width_percentile.extreme_low}"
                    " (extreme squeeze)"
                )
            elif bwp < cfg.bb_width_percentile.very_low:
                score += 12.0
                reasons.append(f"BB_width_pct={bwp:.0f} < {cfg.bb_width_percentile.very_low}")

        if snapshot.iv_percentile is not None:
            ivp = snapshot.iv_percentile
            if ivp <= cfg.iv_percentile.very_low:
                score += 10.0
                reasons.append(f"IV_pct={ivp:.0f} <= {cfg.iv_percentile.very_low} (very low IV)")
            elif ivp <= cfg.iv_percentile.low:
                score += 5.0
                reasons.append(f"IV_pct={ivp:.0f} <= {cfg.iv_percentile.low} (low IV)")

        return self._finalise(score, reasons)

    @staticmethod
    def _finalise(score: float, reasons: list[str]) -> tuple[int, float, list[str]]:
        confidence = max(0, min(100, round(score)))
        return confidence, score, reasons
