"""RegimeEvaluationUseCase — stateless pure computation use case.

Accepts a FeatureSnapshot, runs TrendLayer → VolatilityLayer →
RegimeResolver → ConfidenceCalculator and returns a raw RegimeSnapshot
(no smoothing applied here — smoothing is the service's responsibility).

This use case is injected with pre-constructed domain components, making
it fully testable without any I/O or infrastructure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.value_objects.regime_snapshot import RegimeSnapshot

if TYPE_CHECKING:
    from core.domain.regime.confidence_calculator import ConfidenceCalculator
    from core.domain.regime.regime_resolver import RegimeResolver
    from core.domain.regime.trend_layer import TrendLayer
    from core.domain.regime.volatility_layer import VolatilityLayer
    from core.domain.value_objects.feature_snapshot import FeatureSnapshot


class RegimeEvaluationUseCase:
    """Pure stateless regime computation — no I/O, no smoothing."""

    def __init__(
        self,
        trend_layer: TrendLayer,
        volatility_layer: VolatilityLayer,
        resolver: RegimeResolver,
        confidence_calculator: ConfidenceCalculator,
    ) -> None:
        self._trend = trend_layer
        self._volatility = volatility_layer
        self._resolver = resolver
        self._confidence = confidence_calculator

    def execute(self, snapshot: FeatureSnapshot) -> RegimeSnapshot:
        """Evaluate regime from features snapshot.

        Returns an unsmoothed RegimeSnapshot. The caller (MarketRegimeService)
        applies RegimeSmoother to produce the final smoothed result.
        """
        direction_signal = self._trend.evaluate(snapshot)
        volatility_signal = self._volatility.evaluate(snapshot)
        primary_regime, secondary_regime = self._resolver.resolve(
            direction_signal, volatility_signal
        )
        confidence, score, reasons = self._confidence.calculate(
            primary_regime, direction_signal, volatility_signal, snapshot
        )

        return RegimeSnapshot(
            instrument_token=snapshot.instrument_token,
            timeframe=snapshot.timeframe,
            primary_regime=primary_regime,
            secondary_regime=secondary_regime,
            direction_layer=direction_signal.direction,
            volatility_layer=volatility_signal.level,
            confidence=confidence,
            score=score,
            stability_score=0.0,      # populated by smoother
            regime_duration_bars=0,   # populated by smoother
            transition_signal=False,  # populated by smoother
            explanation=tuple(reasons),
            evaluated_at=snapshot.snapshot_time or datetime.now(UTC),
        )
