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


def _mtf_confidence_adj(context: "ScoreContext") -> float:
    """Compute MTF confidence adjustment from 5m MtfSnapshot.

    Slot: momentum_adj (previously stubbed at 0).

    Alignment between 15m and 5m trends → +5 confidence.
    Conflict (5m opposes 15m) → -5 confidence.
    No 5m data or neutral → 0.

    Regime scaling matches TrendComponent:
      HIGH_VOLATILITY: full confidence effect (score already zeroed by TrendComponent)
      SIDEWAYS:        halved (×0.5)
      TRENDING / LOW:  full (×1.0)
    """
    from core.domain.enums.market_regime import MarketRegime

    mtf_5m = context.features.mtf_5m
    if mtf_5m is None:
        return 0.0

    di_plus_15  = context.features.di_plus  or 0.0
    di_minus_15 = context.features.di_minus or 0.0
    long_15m    = di_plus_15 > di_minus_15

    bias_5m = mtf_5m.bias()
    aligned  = (long_15m and bias_5m == "BULLISH") or (not long_15m and bias_5m == "BEARISH")
    conflict = (long_15m and bias_5m == "BEARISH") or (not long_15m and bias_5m == "BULLISH")

    if aligned:
        raw = 5.0
    elif conflict:
        raw = -5.0
    else:
        return 0.0

    regime = context.regime
    if regime == MarketRegime.SIDEWAYS:
        raw *= 0.5

    return max(-5.0, min(5.0, raw))


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

        # Fetch all async data in parallel.
        # return_exceptions=True: a single failing DB query yields None/[] for that
        # input instead of cancelling all five queries and discarding the signal.
        _gathered = await asyncio.gather(
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
            return_exceptions=True,
        )
        _failed = [r for r in _gathered if isinstance(r, Exception)]
        if _failed:
            _log.warning(
                "confidence.partial_data instrument=%s failed=%d/%d first_error=%s",
                instrument, len(_failed), len(_gathered), _failed[0],
            )
        win_rate            = None  if isinstance(_gathered[0], Exception) else _gathered[0]
        historical_accuracy = None  if isinstance(_gathered[1], Exception) else _gathered[1]
        consecutive_losses  = 0     if isinstance(_gathered[2], Exception) else _gathered[2]
        recent_short        = []    if isinstance(_gathered[3], Exception) else _gathered[3]
        recent_long         = []    if isinstance(_gathered[4], Exception) else _gathered[4]

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

        # Phase 14 MTF confidence adjustment — slots into momentum_adj (previously 0).
        # Applied BEFORE calibration so the bucket selection reflects MTF quality.
        _mtf_adj = _mtf_confidence_adj(context)
        if _mtf_adj != 0.0:
            _new_raw = max(0.0, min(100.0, prelim.raw_confidence + _mtf_adj))
            prelim = dataclasses.replace(
                prelim,
                momentum_adj=_mtf_adj,
                raw_confidence=_new_raw,
                confidence_components={**prelim.confidence_components, "momentum_adj": _mtf_adj},
            )
            _log.debug(
                "confidence.mtf_adj instrument=%d adj=%.1f new_raw=%.2f",
                context.instrument_token, _mtf_adj, _new_raw,
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
