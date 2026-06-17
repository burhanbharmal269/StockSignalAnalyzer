"""ConfidenceEngineService — Phase 12 Confidence Engine orchestrator.

Delegates the 10-component formula to ConfidenceCalculator (pure domain service).
Handles all I/O: repository lookups, Redis calibration, event publication.
Attaches explanation via dataclasses.replace() after calibration is applied.

Responsibility boundary: confidence calculation and trustworthiness evaluation only.
This service must NOT generate signal labels, apply risk rules, or interact with brokers.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3 — Confidence Engine
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING

from core.domain.events.signal_events import ConfidenceCalculated
from core.domain.interfaces.i_confidence_engine import IConfidenceEngine

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.domain.confidence.confidence_calculator import ConfidenceCalculator
    from core.domain.confidence.confidence_explanation_builder import ConfidenceExplanationBuilder
    from core.domain.interfaces.i_signal_performance_repository import (
        ISignalPerformanceRepository,
    )
    from core.domain.value_objects.component_output import ComponentOutput
    from core.domain.value_objects.confidence_result import ConfidenceResult
    from core.domain.value_objects.score_context import ScoreContext
    from core.domain.value_objects.score_result import ScoreResult
    from core.infrastructure.config.confidence_config import ConfidenceConfig
    from core.infrastructure.events.redis_event_bus import RedisStreamEventBus

_log = logging.getLogger(__name__)

_CALIBRATION_KEY_PREFIX = "confidence:calibration"


class ConfidenceEngineService(IConfidenceEngine):
    """Orchestrates async data fetching, delegates computation, publishes events."""

    def __init__(
        self,
        performance_repository: ISignalPerformanceRepository,
        redis_client: Redis,
        config: ConfidenceConfig,
        event_bus: RedisStreamEventBus,
        calculator: ConfidenceCalculator,
        explanation_builder: ConfidenceExplanationBuilder,
    ) -> None:
        self._repo = performance_repository
        self._redis = redis_client
        self._cfg = config
        self._event_bus = event_bus
        self._calc = calculator
        self._builder = explanation_builder

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def calculate_confidence(
        self,
        context: ScoreContext,
        score_result: ScoreResult,
        component_outputs: list[ComponentOutput],
    ) -> ConfidenceResult:
        """Run the full confidence pipeline and publish ConfidenceCalculated event."""
        cfg = self._cfg
        instrument = str(context.instrument_token)
        instrument_class = context.instrument_class.value if context.instrument_class else ""

        # Resolve fingerprint before the parallel gather (needed for historical_accuracy)
        fingerprint_sha = self._calc.fingerprint_for(context, score_result)

        # Fetch all async data in parallel
        (
            win_rate,
            historical_accuracy,
            consecutive_losses,
            recent_short,
            recent_long,
        ) = await asyncio.gather(
            self._repo.get_win_rate(
                regime=context.regime.value,
                direction=score_result.direction,
                instrument_class=instrument_class,
                lookback_days=cfg.win_rate.lookback_days,
                min_samples=cfg.win_rate.min_signals,
            ),
            self._repo.get_historical_accuracy(
                fingerprint=fingerprint_sha,
                min_samples=cfg.historical_accuracy.min_samples_partial,
                lookback_days=cfg.historical_accuracy.lookback_days,
            ),
            self._repo.get_consecutive_losses(
                instrument=instrument,
                lookback_trading_days=cfg.loss_streak.lookback_trading_days,
            ),
            self._repo.get_recent_outcomes(
                instrument=instrument,
                limit=cfg.recent_performance.window_short,
            ),
            self._repo.get_recent_outcomes(
                instrument=instrument,
                limit=cfg.recent_performance.window_long,
            ),
        )

        # Delegate formula to pure domain service (AC-11: deterministic)
        prelim = self._calc.calculate(
            context=context,
            score_result=score_result,
            component_outputs=component_outputs,
            win_rate=win_rate,
            historical_accuracy=historical_accuracy,
            consecutive_losses=consecutive_losses,
            recent_outcomes_short=recent_short,
            recent_outcomes_long=recent_long,
        )

        # Apply Redis calibration factor (fail-open: defaults to 1.0)
        calibration_factor = await self._calibration_factor(prelim.raw_confidence)
        calibrated = max(0.0, min(100.0, prelim.raw_confidence * calibration_factor))

        # Apply score-band ceiling
        if prelim.score_bucket == "STRONG":
            final = calibrated
        else:
            final = min(calibrated, cfg.ceiling.standard_max_confidence)
        final = max(0.0, min(100.0, final))  # AC-12: always clamped [0, 100]

        passed_gate = final >= cfg.gate.min_confidence

        result: ConfidenceResult = dataclasses.replace(
            prelim,
            calibrated_confidence=round(calibrated, 4),
            final_confidence=round(final, 4),
            passed_gate=passed_gate,
        )

        # Attach explanation (pure builder, no I/O)
        explanation = self._builder.build(result, context, score_result)
        result = dataclasses.replace(result, explanation=explanation)

        await self._event_bus.publish(
            ConfidenceCalculated(
                instrument_token=context.instrument_token,
                direction=score_result.direction,
                score_bucket=result.score_bucket,
                fingerprint=result.fingerprint,
                base_confidence=result.base_confidence,
                raw_confidence=result.raw_confidence,
                calibrated_confidence=result.calibrated_confidence,
                final_confidence=result.final_confidence,
                passed_gate=result.passed_gate,
                win_rate_adj=result.win_rate_adj,
                regime_alignment_adj=result.regime_alignment_adj,
                data_quality_adj=result.data_quality_adj,
                momentum_adj=result.momentum_adj,
                breakout_adj=result.breakout_adj,
                loss_streak_adj=result.loss_streak_adj,
                historical_accuracy_adj=result.historical_accuracy_adj,
                signal_agreement_adj=result.signal_agreement_adj,
                recent_performance_adj=result.recent_performance_adj,
            )
        )

        _log.debug(
            "confidence computed instrument=%d direction=%s final=%.2f gate=%s",
            context.instrument_token,
            score_result.direction,
            result.final_confidence,
            result.passed_gate,
        )

        return result

    # ------------------------------------------------------------------
    # Calibration (Redis — fail-open)
    # ------------------------------------------------------------------

    async def _calibration_factor(self, raw_confidence: float) -> float:
        bucket = self._confidence_bucket_label(raw_confidence)
        if bucket is None:
            return 1.0
        key = f"{_CALIBRATION_KEY_PREFIX}:{bucket}"
        try:
            val = await self._redis.get(key)
            return float(val) if val is not None else 1.0
        except Exception:
            _log.warning("calibration Redis lookup failed for key=%s, using 1.0", key)
            return 1.0

    @staticmethod
    def _confidence_bucket_label(confidence: float) -> str | None:
        for lo, hi in ((65, 69), (70, 74), (75, 79), (80, 84), (85, 89), (90, 100)):
            if lo <= confidence <= hi:
                return f"{lo}-{hi}"
        return None
