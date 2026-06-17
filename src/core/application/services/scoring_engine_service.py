"""ScoringEngineService — Phase 11 application-layer orchestrator.

Responsibilities:
  1. Receive a ScoreContext.
  2. Call each of the 7 IScoreComponent.evaluate() in sequence.
  3. Pass component outputs to ScoreCalculator (pure domain).
  4. Build explanation via ScoreExplanationBuilder.
  5. Publish ScoreCalculated domain event.
  6. Return ScoreResult to caller.

This service is FORBIDDEN from: Order Placement, Risk Management,
Position Sizing, Final Trade Decision, Stoploss Calculation, Margin Decisions.
Signal labels (BUY / SELL / STRONG_BUY) are Phase 14 — not produced here.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from core.domain.events.signal_events import ScoreCalculated
from core.domain.interfaces.i_scoring_engine import IScoringEngine
from core.domain.scoring.score_explanation_builder import ScoreExplanationBuilder
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.domain.interfaces.i_event_bus import IEventBus
    from core.domain.interfaces.i_score_component import IScoreComponent
    from core.domain.scoring.score_calculator import ScoreCalculator
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult

logger = get_logger(__name__)


class ScoringEngineService(IScoringEngine):
    """Orchestrates the 7 scoring components into a composite ScoreResult."""

    def __init__(
        self,
        oi_buildup_component: IScoreComponent,
        trend_component: IScoreComponent,
        option_chain_component: IScoreComponent,
        volume_component: IScoreComponent,
        vwap_component: IScoreComponent,
        sentiment_component: IScoreComponent,
        iv_analysis_component: IScoreComponent,
        score_calculator: ScoreCalculator,
        event_bus: IEventBus,
    ) -> None:
        self._components: list[IScoreComponent] = [
            oi_buildup_component,
            trend_component,
            option_chain_component,
            volume_component,
            vwap_component,
            sentiment_component,
            iv_analysis_component,
        ]
        self._calculator = score_calculator
        self._event_bus = event_bus
        self._explanation_builder = ScoreExplanationBuilder()

    async def calculate_score(self, context: ScoreContext) -> ScoreResult:
        """Evaluate all components and return a scored, event-published ScoreResult."""
        logger.info(
            "scoring_engine.start",
            instrument_token=context.instrument_token,
            regime=context.regime.value,
            timeframe=context.timeframe,
        )

        # Evaluate all 7 components
        component_outputs = []
        for component in self._components:
            output = component.evaluate(context)
            component_outputs.append(output)
            if not output.is_available:
                logger.warning(
                    "scoring_engine.component_unavailable",
                    component=output.component_name,
                    reason=output.key_finding,
                    instrument_token=context.instrument_token,
                )

        # Pure domain calculation
        result = self._calculator.calculate(component_outputs, context)

        # Attach explanation (requires dataclasses.replace on frozen dataclass)
        explanation = self._explanation_builder.build(result, component_outputs, context)
        result = dataclasses.replace(result, explanation=explanation)

        # Publish domain event
        bd = result.score_breakdown
        event = ScoreCalculated(
            instrument_token=context.instrument_token,
            direction=result.direction,
            direction_conviction=result.direction_conviction,
            raw_score=result.raw_score,
            adjusted_score=result.adjusted_score,
            score_quality=result.score_quality,
            regime=context.regime.value,
            data_completeness_pct=result.data_completeness_pct,
            weights_sha256=result.weights_sha256,
            penalties_count=len(result.penalties),
            is_eligible=result.is_eligible,
            breakdown_oi_buildup=bd.oi_buildup,
            breakdown_trend=bd.trend,
            breakdown_option_chain=bd.option_chain,
            breakdown_volume=bd.volume,
            breakdown_vwap=bd.vwap,
            breakdown_sentiment=bd.sentiment,
            breakdown_iv_analysis=bd.iv_analysis,
            breakdown_regime_alignment=bd.regime_alignment,
            breakdown_regime_mismatch=bd.regime_mismatch,
            breakdown_total=bd.total_before_penalties,
            correlation_id=str(context.instrument_token),
        )
        await self._event_bus.publish(event)

        logger.info(
            "scoring_engine.complete",
            instrument_token=context.instrument_token,
            direction=result.direction,
            conviction=result.direction_conviction,
            raw_score=result.raw_score,
            adjusted_score=result.adjusted_score,
            score_quality=result.score_quality,
            is_eligible=result.is_eligible,
            penalties=len(result.penalties),
        )

        return result
