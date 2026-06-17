"""VWAP Analysis Component — Component 5 (base weight: 10).

VWAP is the single most important intraday level for institutional execution.
Operates in two modes determined by the current market regime:

  Mode A — Mean Reversion (SIDEWAYS / HIGH_VOLATILITY)
    Price at -1.5σ + volume + RSI oversold → max long score
    Price at +1.5σ + volume + RSI overbought → max short score
    Touch count degrades the score (each repeated test weakens support)

  Mode B — Trend Confirmation (TRENDING_BULLISH / TRENDING_BEARISH)
    Price above VWAP → confirms LONG direction (dynamic support)
    Price below VWAP → confirms SHORT direction (dynamic resistance)
    Near-VWAP bounce → higher score than hovering above

Source: docs/21_SIGNAL_ENGINE.md Component 5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime
from core.domain.interfaces.i_score_component import IScoreComponent
from core.domain.value_objects.component_output import ComponentOutput

if TYPE_CHECKING:
    from core.domain.value_objects.score_context import ScoreContext
    from core.infrastructure.config.strategy_config import StrategyConfig

_NAME = "VWAP"
_MAX_WEIGHT = 10

_MODE_A_REGIMES = {MarketRegime.SIDEWAYS, MarketRegime.HIGH_VOLATILITY, MarketRegime.LOW_VOLATILITY}
_MODE_B_REGIMES = {MarketRegime.TRENDING_BULLISH, MarketRegime.TRENDING_BEARISH}


class VWAPComponent(IScoreComponent):
    """VWAP mean-reversion and trend-confirmation scorer. Pure, stateless."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config.vwap

    @property
    def component_name(self) -> str:
        return _NAME

    @property
    def max_weight(self) -> int:
        return _MAX_WEIGHT

    def evaluate(self, context: ScoreContext) -> ComponentOutput:
        cfg = self._cfg

        if context.vwap_deviation_sigma is None:
            return ComponentOutput.unavailable(
                _NAME, _MAX_WEIGHT, "vwap_deviation_sigma not available"
            )

        sigma = context.vwap_deviation_sigma
        touch = context.vwap_touch_count
        regime = context.regime
        vr = context.volume_ratio
        rsi = context.rsi_14

        if regime in _MODE_A_REGIMES:
            long_raw, short_raw, mode = self._mode_a(sigma, vr, rsi, touch, cfg)
        else:
            long_raw, short_raw, mode = self._mode_b(sigma, cfg)

        long_score = max(0.0, min(float(_MAX_WEIGHT), long_raw))
        short_score = max(0.0, min(float(_MAX_WEIGHT), short_raw))

        direction, conviction = _direction_and_conviction(long_score, short_score, _MAX_WEIGHT)

        key_finding = (
            f"VWAP deviation {sigma:+.2f}σ. "
            f"{'Mode A (mean-reversion)' if mode == 'A' else 'Mode B (trend confirm)'}. "
            f"Touch count: {touch}. "
            f"Volume: {f'{vr:.1f}×' if vr is not None else 'N/A'}."
        )

        return ComponentOutput(
            component_name=_NAME,
            max_weight=_MAX_WEIGHT,
            long_score=long_score,
            short_score=short_score,
            direction=direction,
            conviction=conviction,
            is_available=True,
            data_freshness_seconds=0,
            key_finding=key_finding,
            metadata={
                "vwap_deviation_sigma": sigma,
                "vwap_touch_count": touch,
                "mode": mode,
                "regime": str(regime),
                "volume_ratio": vr,
                "rsi_14": rsi,
            },
        )

    # ------------------------------------------------------------------
    # Mode A — Mean Reversion
    # ------------------------------------------------------------------

    @staticmethod
    def _mode_a(
        sigma: float,
        volume_ratio: float | None,
        rsi: float | None,
        touch_count: int,
        cfg: object,
    ) -> tuple[float, float, str]:
        vr = volume_ratio or 0.0

        # LONG: price below VWAP (negative sigma)
        long_raw = VWAPComponent._mode_a_directional(
            deviation=-sigma,               # negative sigma → positive for long
            volume_ratio=vr,
            rsi=rsi,
            rsi_extreme=cfg.mode_a_rsi_long_extreme,
            rsi_strong=cfg.mode_a_rsi_long_strong,
            rsi_moderate=cfg.mode_a_rsi_long_moderate,
            rsi_gate_direction="below",
            cfg=cfg,
        )

        # SHORT: price above VWAP (positive sigma)
        short_raw = VWAPComponent._mode_a_directional(
            deviation=sigma,                # positive sigma → positive for short
            volume_ratio=vr,
            rsi=rsi,
            rsi_extreme=cfg.mode_a_rsi_short_extreme,
            rsi_strong=cfg.mode_a_rsi_short_strong,
            rsi_moderate=cfg.mode_a_rsi_short_moderate,
            rsi_gate_direction="above",
            cfg=cfg,
        )

        # Apply touch count degradation
        multiplier = _touch_multiplier(touch_count, cfg)
        return long_raw * multiplier, short_raw * multiplier, "A"

    @staticmethod
    def _mode_a_directional(
        deviation: float,      # positive = price has moved in the signal direction
        volume_ratio: float,
        rsi: float | None,
        rsi_extreme: float,
        rsi_strong: float,
        rsi_moderate: float,
        rsi_gate_direction: str,  # "below" for LONG (RSI < threshold), "above" for SHORT
        cfg: object,
    ) -> float:
        """Score for one direction in Mode A."""
        if deviation <= 0:
            return 0.0  # Price is on the wrong side of VWAP for this direction

        def rsi_ok(threshold: float) -> bool:
            if rsi is None:
                return False
            if rsi_gate_direction == "below":
                return rsi < threshold
            return rsi > threshold

        extreme_sigma = cfg.mode_a_extreme_sigma
        strong_sigma = cfg.mode_a_strong_sigma
        moderate_sigma = cfg.mode_a_moderate_sigma
        vol_extreme = cfg.mode_a_volume_ratio_extreme
        vol_strong = cfg.mode_a_volume_ratio_strong

        if deviation >= extreme_sigma and volume_ratio >= vol_extreme and rsi_ok(rsi_extreme):
            return cfg.mode_a_score_extreme
        if deviation >= strong_sigma and volume_ratio >= vol_strong and rsi_ok(rsi_strong):
            return cfg.mode_a_score_strong
        if deviation >= moderate_sigma and rsi_ok(rsi_moderate):
            return cfg.mode_a_score_moderate
        return 0.0

    # ------------------------------------------------------------------
    # Mode B — Trend Confirmation
    # ------------------------------------------------------------------

    @staticmethod
    def _mode_b(sigma: float, cfg: object) -> tuple[float, float, str]:
        """Price above/below VWAP as dynamic support/resistance."""
        proximity = cfg.mode_b_bounce_proximity_sigma

        # LONG: price above VWAP
        if sigma >= 0:
            if sigma <= proximity:
                # Near VWAP — possible bounce zone → highest confidence
                long_score = cfg.mode_b_score_bouncing
            else:
                long_score = cfg.mode_b_score_above_only
            short_score = cfg.mode_b_score_caution
        else:
            # Price below VWAP
            if abs(sigma) <= proximity:
                short_score = cfg.mode_b_score_bouncing
            else:
                short_score = cfg.mode_b_score_above_only
            long_score = cfg.mode_b_score_caution

        return long_score, short_score, "B"


def _touch_multiplier(touch_count: int, cfg: object) -> float:
    if touch_count == 0:
        return cfg.touch_count_multiplier_0
    if touch_count == 1:
        return cfg.touch_count_multiplier_1
    if touch_count == 2:
        return cfg.touch_count_multiplier_2
    return cfg.touch_count_multiplier_3_plus


def _direction_and_conviction(
    long_score: float, short_score: float, max_weight: int
) -> tuple[str, float]:
    if long_score > short_score:
        return "LONG", long_score / max_weight
    if short_score > long_score:
        return "SHORT", short_score / max_weight
    return "NEUTRAL", 0.0
