"""RegimeSmoother — stateful α-blending anti-whipsaw tracker.

Tracks (instrument_token, timeframe) → regime state.
Computes:
    stability  = min(duration_bars / min_required_bars, 1.0)
    α          = min(1.0, stability × confidence / 100)
    effective_confidence = prev_confidence × (1 − α) + new_confidence × α

When stability < 1.0 the regime is "in transition" — consumers can use
stability_score to down-weight regime-dependent multipliers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.domain.enums.market_regime import MarketRegime

if TYPE_CHECKING:
    from core.infrastructure.config.regime_config import RegimeConfig


@dataclass
class _RegimeState:
    """Mutable regime tracking state for one (instrument_token, timeframe) key."""

    primary_regime: MarketRegime = MarketRegime.SIDEWAYS
    duration_bars: int = 0
    prev_confidence: float = 0.0


@dataclass(frozen=True)
class SmoothedResult:
    """Output of RegimeSmoother.update()."""

    primary_regime: MarketRegime
    effective_confidence: int    # α-blended confidence, clamped 0–100
    stability_score: float       # 0.0–1.0
    duration_bars: int
    transition_signal: bool      # True when primary regime changed this bar


class RegimeSmoother:
    """Stateful anti-whipsaw smoother. One instance per engine instance.

    State is kept in memory. It is ephemeral — on restart the smoother
    cold-starts from zero stability, which is intentional: a fresh start
    means we haven't confirmed any regime yet.
    """

    def __init__(self, config: RegimeConfig) -> None:
        self._cfg = config
        self._states: dict[tuple[int, str], _RegimeState] = {}

    def update(
        self,
        instrument_token: int,
        timeframe: str,
        new_primary: MarketRegime,
        raw_confidence: int,
    ) -> SmoothedResult:
        """Consume a new raw regime classification and return smoothed result."""
        key = (instrument_token, timeframe)

        if key not in self._states:
            self._states[key] = _RegimeState()

        state = self._states[key]
        transition_signal = new_primary != state.primary_regime

        if transition_signal:
            state.primary_regime = new_primary
            state.duration_bars = 1
            state.prev_confidence = 0.0
        else:
            state.duration_bars += 1

        min_bars = self._min_bars_for(new_primary)
        stability = min(state.duration_bars / max(min_bars, 1), 1.0)

        alpha = min(1.0, stability * raw_confidence / 100.0)
        effective = state.prev_confidence * (1.0 - alpha) + raw_confidence * alpha
        state.prev_confidence = effective

        return SmoothedResult(
            primary_regime=new_primary,
            effective_confidence=max(0, min(100, round(effective))),
            stability_score=stability,
            duration_bars=state.duration_bars,
            transition_signal=transition_signal,
        )

    def reset(self, instrument_token: int, timeframe: str) -> None:
        """Clear state for a specific key — used in tests and on instrument removal."""
        self._states.pop((instrument_token, timeframe), None)

    def _min_bars_for(self, regime: MarketRegime) -> int:
        tb = self._cfg.transition_min_bars
        if regime in (MarketRegime.TRENDING_BULLISH, MarketRegime.TRENDING_BEARISH):
            return tb.sideways_to_trending
        if regime == MarketRegime.SIDEWAYS:
            return tb.trending_to_sideways
        if regime == MarketRegime.HIGH_VOLATILITY:
            return tb.any_to_high_vol
        if regime == MarketRegime.LOW_VOLATILITY:
            return tb.any_to_low_vol
        return 1
