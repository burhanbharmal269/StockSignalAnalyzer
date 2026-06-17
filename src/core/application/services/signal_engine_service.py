"""SignalEngineService — Phase 14 signal pipeline orchestrator.

Orchestrates: Universe Candidate → Score → Confidence → Risk → Signal.

This service is orchestration ONLY. It does NOT:
- Calculate scores (delegates to IScoringEngine)
- Calculate confidence (delegates to IConfidenceEngine)
- Perform risk checks (delegates to IRiskEngine)
- Place orders (no OMS integration)
- Call broker APIs

Mandatory invariants (from Phase 14 architecture):
1. Persistence-first: Signal is persisted to DB before any event is published.
2. Idempotent: Same dedup key within TTL → no duplicate signal or event.
3. Signal expiration is config-driven (signal.ttl_minutes, market_close_time).
4. Signal Engine does NOT consume full FnO universe; only pre-selected candidates.
5. Fail-open is limited to Redis/event-bus operations. DB persistence NEVER fails open.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from core.application.services.signal.signal_deduplication_service import (
    SignalDeduplicationService,
)
from core.application.services.signal.signal_explanation_builder import (
    SignalExplanationBuilder,
)
from core.domain.entities.signal import Signal
from core.domain.enums.signal_rejection_reason import SignalRejectionReason
from core.domain.enums.signal_state import SignalState
from core.domain.enums.signal_type import SignalType
from core.domain.events.signal_events import SignalRiskApproved, SignalRiskRejected
from core.domain.exceptions.signal import SignalPersistenceError
from core.domain.interfaces.i_confidence_engine import IConfidenceEngine
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_risk_engine import IRiskEngine
from core.domain.interfaces.i_scoring_engine import IScoringEngine
from core.domain.interfaces.i_signal_cache_repository import ISignalCacheRepository
from core.domain.interfaces.i_signal_repository import ISignalRepository
from core.domain.risk.risk_request import RiskRequest
from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score
from core.domain.value_objects.signal_explanation import SignalExplanation
from core.domain.value_objects.signal_request import SignalRequest
from core.domain.value_objects.signal_result import SignalResult
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.config.signal_config import SignalConfig

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")

_PUBLISH_RETRY_DELAYS = (0.0, 0.2, 0.4)


class SignalEngineService:
    """Processes one universe candidate through the full signal pipeline.

    Each call to process() handles exactly one SelectedInstrument candidate.
    The caller (typically an event consumer) loops over the universe and calls
    this service once per candidate.

    Error contract:
    - Engine errors (scoring, confidence, risk): caught internally; returns
      SignalResult(accepted=False) with appropriate rejection reason.
    - Persistence errors (DB): raises SignalPersistenceError — never fail-open.
    - Redis errors (dedup, cache): fail-open; logged as WARNING.
    - Event bus errors: retried 3×; logged as CRITICAL on total failure.
    """

    def __init__(
        self,
        scoring_engine: IScoringEngine,
        confidence_engine: IConfidenceEngine,
        risk_engine: IRiskEngine,
        signal_repository: ISignalRepository,
        signal_cache: ISignalCacheRepository,
        event_bus: IEventBus,
        explanation_builder: SignalExplanationBuilder,
        dedup_service: SignalDeduplicationService,
        config: SignalConfig,
    ) -> None:
        self._scoring = scoring_engine
        self._confidence = confidence_engine
        self._risk = risk_engine
        self._repo = signal_repository
        self._cache = signal_cache
        self._bus = event_bus
        self._explanation = explanation_builder
        self._dedup = dedup_service
        self._config = config

    async def process(self, request: SignalRequest) -> SignalResult:
        """Run the signal pipeline for one universe candidate.

        Returns SignalResult for domain-level rejections (ineligible score,
        weak gate, risk rejected, dedup).
        Raises SignalPersistenceError if DB persistence fails — callers must
        NOT treat this as a silent rejection.
        """
        try:
            return await self._process_internal(request)
        except SignalPersistenceError:
            raise  # Persistence failures always propagate
        except Exception:
            _log.exception(
                "Unexpected engine error processing signal for token=%s",
                request.instrument_token,
            )
            return SignalResult(
                accepted=False,
                signal_id=None,
                rejection_reason=SignalRejectionReason.SCORE_INELIGIBLE,
                explanation=SignalExplanation(
                    score_lines=(),
                    confidence_lines=(),
                    risk_lines=(),
                    rejection_reason="internal_error",
                ),
                is_duplicate=False,
            )

    async def _process_internal(self, request: SignalRequest) -> SignalResult:
        # ── Stage 1: Score Engine ──────────────────────────────────────
        score_result = await self._scoring.calculate_score(request.score_context)

        if not score_result.is_eligible or score_result.direction == "NEUTRAL":
            explanation = self._explanation.build(
                score_result=score_result,
                rejection_reason="score_ineligible",
            )
            return SignalResult(
                accepted=False,
                signal_id=None,
                rejection_reason=SignalRejectionReason.SCORE_INELIGIBLE,
                explanation=explanation,
                is_duplicate=False,
                adjusted_score=score_result.adjusted_score,
            )

        # ── Stage 2: Deduplication check ──────────────────────────────
        is_dup = await self._dedup.is_duplicate(
            instrument_token=request.instrument_token,
            direction=score_result.direction,
            strategy_type=str(request.strategy_type),
            regime=str(request.regime),
            weights_sha256=score_result.weights_sha256,
        )
        if is_dup:
            return SignalResult(
                accepted=False,
                signal_id=None,
                rejection_reason=SignalRejectionReason.DUPLICATE,
                explanation=SignalExplanation(
                    score_lines=(),
                    confidence_lines=(),
                    risk_lines=(),
                    rejection_reason="duplicate_within_ttl",
                ),
                is_duplicate=True,
                adjusted_score=score_result.adjusted_score,
            )

        # ── Stage 3: Confidence Engine ─────────────────────────────────
        confidence_result = await self._confidence.calculate_confidence(
            context=request.score_context,
            score_result=score_result,
            component_outputs=[],
        )

        # ── Stage 4: Create Signal entity ─────────────────────────────
        now = datetime.now(UTC)
        valid_until = self._compute_valid_until(now)
        signal = Signal.create(
            symbol=Symbol(ticker=request.underlying, exchange="NSE"),
            signal_type=SignalType(score_result.direction),
            strategy_type=request.strategy_type,
            asset_type=request.asset_type,
            regime=request.regime,
            valid_until=valid_until,
            correlation_id=request.correlation_id,
        )

        # Check TTL at creation time
        if signal.is_expired_by_ttl:
            explanation = self._explanation.build(
                score_result=score_result,
                confidence_result=confidence_result,
                rejection_reason="expired_before_processing",
            )
            return SignalResult(
                accepted=False,
                signal_id=signal.signal_id,
                rejection_reason=SignalRejectionReason.EXPIRED,
                explanation=explanation,
                is_duplicate=False,
                adjusted_score=score_result.adjusted_score,
                final_confidence=confidence_result.final_confidence,
            )

        # ── Stage 5: Apply scoring to entity ──────────────────────────
        signal.start_scoring()
        signal.complete_scoring(
            raw_score=Score(score_result.raw_score),
            adjusted_score=Score(score_result.adjusted_score),
            confidence=Confidence(confidence_result.final_confidence),
            scoring_weights_sha256=score_result.weights_sha256,
            fingerprint=confidence_result.fingerprint,
        )

        # ── Stage 6: Gate check → RISK_PENDING or WEAK_SIGNAL ─────────
        signal.submit_to_risk(
            self._config.gate.min_score,
            self._config.gate.min_confidence,
        )

        if signal.state == SignalState.WEAK_SIGNAL:
            explanation = self._explanation.build(
                score_result=score_result,
                confidence_result=confidence_result,
                rejection_reason=(
                    f"score={score_result.adjusted_score:.1f} "
                    f"confidence={confidence_result.final_confidence:.1f} "
                    f"gate=({self._config.gate.min_score}/{self._config.gate.min_confidence})"
                ),
            )
            await self._persist(signal)
            events = signal.pull_events()
            await self._publish_events(events)
            return SignalResult(
                accepted=False,
                signal_id=signal.signal_id,
                rejection_reason=SignalRejectionReason.WEAK_SIGNAL,
                explanation=explanation,
                is_duplicate=False,
                adjusted_score=score_result.adjusted_score,
                final_confidence=confidence_result.final_confidence,
            )

        # ── Stage 7: Risk Engine ───────────────────────────────────────
        risk_request = self._build_risk_request(
            signal=signal,
            request=request,
            score_result=score_result,
            confidence_result=confidence_result,
            now=now,
        )
        risk_decision = await self._risk.evaluate(risk_request)

        # ── Stage 8: Transition signal based on risk decision ──────────
        if risk_decision.approved:
            signal.approve_risk()
        else:
            signal.reject_risk(
                reason=risk_decision.rejection_reason or str(risk_decision.rejection_code)
            )

        # ── Stage 9: Persistence-first ────────────────────────────────
        await self._persist(signal)

        # ── Stage 10: Publish domain events from entity ───────────────
        events = signal.pull_events()
        await self._publish_events(events)

        # ── Stage 11: Publish SignalRiskApproved / SignalRiskRejected ──
        if risk_decision.approved:
            approved_event = SignalRiskApproved(
                signal_id=signal.signal_id,
                instrument_token=request.instrument_token,
                underlying=request.underlying,
                direction=score_result.direction,
                adjusted_score=score_result.adjusted_score,
                final_confidence=confidence_result.final_confidence,
                risk_decision_id=risk_decision.risk_decision_id,
                strategy_type=str(request.strategy_type),
                regime=str(request.regime),
                position_size_lots=risk_decision.position_size_lots,
                valid_until=signal.valid_until,
                correlation_id=request.correlation_id,
            )
            await self._publish_events([approved_event])

            # Register dedup + active signal in Redis (best-effort, fail-open)
            try:
                await self._dedup.register(
                    instrument_token=request.instrument_token,
                    direction=score_result.direction,
                    strategy_type=str(request.strategy_type),
                    regime=str(request.regime),
                    weights_sha256=score_result.weights_sha256,
                    signal_id=str(signal.signal_id),
                )
            except Exception:
                _log.warning(
                    "Dedup registration failed for signal %s — continuing (fail-open)",
                    signal.signal_id,
                )
            try:
                await self._cache.set_active_signal(
                    instrument_token=request.instrument_token,
                    signal_id=str(signal.signal_id),
                    ttl_seconds=self._config.ttl_seconds,
                )
            except Exception:
                _log.warning(
                    "Active signal cache write failed for %s — continuing (fail-open)",
                    signal.signal_id,
                )
        else:
            rejected_event = SignalRiskRejected(
                signal_id=signal.signal_id,
                reason=risk_decision.rejection_reason or str(risk_decision.rejection_code),
                correlation_id=request.correlation_id,
            )
            await self._publish_events([rejected_event])

        explanation = self._explanation.build(
            score_result=score_result,
            confidence_result=confidence_result,
            risk_decision=risk_decision,
            rejection_reason=None if risk_decision.approved else str(risk_decision.rejection_code),
        )

        return SignalResult(
            accepted=risk_decision.approved,
            signal_id=signal.signal_id,
            rejection_reason=(
                None if risk_decision.approved else SignalRejectionReason.RISK_REJECTED
            ),
            explanation=explanation,
            is_duplicate=False,
            adjusted_score=score_result.adjusted_score,
            final_confidence=confidence_result.final_confidence,
            risk_approved=risk_decision.approved,
            position_size_lots=risk_decision.position_size_lots,
            direction=score_result.direction,
            score_breakdown=score_result.score_breakdown,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _persist(self, signal: Signal) -> None:
        """Persist signal to DB. Raises SignalPersistenceError on failure.

        This is the only place where DB persistence is called. It NEVER
        fails open — a DB failure raises SignalPersistenceError so the caller
        can retry or surface the error rather than silently losing the signal.
        """
        try:
            await self._repo.save(signal)
        except Exception as exc:
            raise SignalPersistenceError(
                f"Failed to persist signal {signal.signal_id}: {exc}"
            ) from exc

    def _compute_valid_until(self, now: datetime) -> datetime:
        """min(now + ttl_minutes, 15:15:00 IST today) during market hours.

        After market close, use the full TTL so post-session signals remain
        valid for the configured window (e.g. pre-open preparation).
        """
        ttl_expiry = now + timedelta(minutes=self._config.ttl_minutes)
        close_parts = self._config.market_close_time.split(":")
        ist_today = now.astimezone(_IST)
        market_close_ist = ist_today.replace(
            hour=int(close_parts[0]),
            minute=int(close_parts[1]),
            second=0,
            microsecond=0,
        )
        market_close_utc = market_close_ist.astimezone(UTC)
        if now >= market_close_utc:
            return ttl_expiry
        return min(ttl_expiry, market_close_utc)

    def _build_risk_request(
        self,
        signal: Signal,
        request: SignalRequest,
        score_result: object,
        confidence_result: object,
        now: datetime,
    ) -> RiskRequest:
        risk_reward = (
            float(request.target_price - request.entry_price)
            / float(request.entry_price - request.stop_loss_price)
            if request.entry_price != request.stop_loss_price
            else 1.0
        )
        return RiskRequest(
            signal_id=signal.signal_id,
            instrument_token=request.instrument_token,
            underlying=request.underlying,
            instrument_class=request.instrument_class,
            direction=score_result.direction,
            adjusted_score=score_result.adjusted_score,
            final_confidence=confidence_result.final_confidence,
            entry_price=request.entry_price,
            stop_loss_price=request.stop_loss_price,
            target_price=request.target_price,
            option_premium=request.option_premium,
            lot_size=request.lot_size,
            option_delta=request.option_delta,
            option_vega=request.option_vega,
            dte=request.dte,
            atr_14=request.atr_14,
            risk_reward_ratio=risk_reward,
            evaluated_at=now,
        )

    async def _publish_events(self, events: list[object]) -> None:
        """Publish events with 3-retry fallback. Logs CRITICAL on total failure."""
        for event in events:
            for i, delay in enumerate(_PUBLISH_RETRY_DELAYS):
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self._bus.publish(event)
                    break
                except Exception:
                    if i < len(_PUBLISH_RETRY_DELAYS) - 1:
                        _log.warning(
                            "Event publish attempt %d failed for %s — retrying",
                            i + 1,
                            type(event).__name__,
                        )
                    else:
                        _log.critical(
                            "All %d publish attempts failed for %s",
                            len(_PUBLISH_RETRY_DELAYS),
                            type(event).__name__,
                        )
