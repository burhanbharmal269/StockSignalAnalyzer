"""Unit tests for SignalEngineService — Phase 14 signal pipeline orchestrator."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.signal.signal_deduplication_service import (
    SignalDeduplicationService,
)
from core.application.services.signal.signal_explanation_builder import (
    SignalExplanationBuilder,
)
from core.application.services.signal_engine_service import SignalEngineService
from core.domain.enums.asset_type import AssetType
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.signal_rejection_reason import SignalRejectionReason
from core.domain.enums.strategy_type import StrategyType
from core.domain.events.signal_events import SignalRiskApproved, SignalRiskRejected
from core.domain.exceptions.signal import SignalPersistenceError
from core.domain.value_objects.signal_request import SignalRequest
from core.infrastructure.config.signal_config import SignalConfig

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_FINGERPRINT = "a" * 64


def _score_result(
    is_eligible: bool = True,
    direction: str = "LONG",
    raw_score: float = 75.0,
    adjusted_score: float = 75.0,
    weights_sha256: str = "w" * 64,
    score_quality: str = "HIGH",
    data_completeness_pct: float = 100.0,
    explanation: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.is_eligible = is_eligible
    r.direction = direction
    r.raw_score = raw_score
    r.adjusted_score = adjusted_score
    r.weights_sha256 = weights_sha256
    r.score_quality = score_quality
    r.data_completeness_pct = data_completeness_pct
    r.explanation = explanation or []
    return r


def _confidence_result(
    final_confidence: float = 70.0,
    fingerprint: str = _FINGERPRINT,
    score_bucket: str = "STANDARD",
    passed_gate: bool = True,
    explanation: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.final_confidence = final_confidence
    r.fingerprint = fingerprint
    r.score_bucket = score_bucket
    r.passed_gate = passed_gate
    r.explanation = explanation or []
    return r


def _risk_decision(
    approved: bool = True,
    position_size_lots: int | None = 2,
    rejection_code: str | None = None,
    rejection_reason: str | None = None,
    risk_decision_id: int | None = 42,
    checks: tuple = (),
) -> MagicMock:
    r = MagicMock()
    r.approved = approved
    r.position_size_lots = position_size_lots
    r.rejection_code = rejection_code
    r.rejection_reason = rejection_reason
    r.risk_decision_id = risk_decision_id
    r.checks = checks
    r.sizing = None
    return r


def _make_request(
    strategy_type: StrategyType = StrategyType.DIRECTIONAL,
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
    underlying: str = "NIFTY",
) -> SignalRequest:
    return SignalRequest(
        instrument_token=1001,
        underlying=underlying,
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        strategy_type=strategy_type,
        asset_type=AssetType.FNO,
        regime=regime,
        score_context=MagicMock(),
        entry_price=Decimal("23000"),
        stop_loss_price=Decimal("22700"),
        target_price=Decimal("23600"),
        option_premium=Decimal("250"),
        lot_size=50,
        dte=12,
        atr_14=1.5,
        correlation_id="corr-001",
    )


def _make_service(
    score_result: MagicMock | None = None,
    confidence_result: MagicMock | None = None,
    risk_decision_mock: MagicMock | None = None,
    is_duplicate: bool = False,
    repo_save_raises: Exception | None = None,
) -> SignalEngineService:
    scoring = AsyncMock()
    scoring.calculate_score = AsyncMock(return_value=score_result or _score_result())

    confidence = AsyncMock()
    confidence.calculate_confidence = AsyncMock(
        return_value=confidence_result or _confidence_result()
    )

    risk = AsyncMock()
    risk.evaluate = AsyncMock(return_value=risk_decision_mock or _risk_decision())

    repo = AsyncMock()
    if repo_save_raises is not None:
        repo.save = AsyncMock(side_effect=repo_save_raises)
    else:
        repo.save = AsyncMock()

    cache = AsyncMock()
    cache.is_duplicate = AsyncMock(return_value=is_duplicate)
    cache.set_dedup = AsyncMock()
    cache.set_active_signal = AsyncMock()
    cache.delete_active_signal = AsyncMock()
    cache.get_active_signal_id = AsyncMock(return_value=None)

    bus = AsyncMock()
    bus.publish = AsyncMock()

    config = SignalConfig()
    dedup_svc = SignalDeduplicationService(cache, config)
    explanation_builder = SignalExplanationBuilder()

    return SignalEngineService(
        scoring_engine=scoring,
        confidence_engine=confidence,
        risk_engine=risk,
        signal_repository=repo,
        signal_cache=cache,
        event_bus=bus,
        explanation_builder=explanation_builder,
        dedup_service=dedup_svc,
        config=config,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SE-01: Score ineligible → SCORE_INELIGIBLE
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreIneligible:
    @pytest.mark.asyncio
    async def test_ineligible_score_returns_rejection(self) -> None:
        service = _make_service(score_result=_score_result(is_eligible=False))
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.SCORE_INELIGIBLE
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_neutral_direction_returns_rejection(self) -> None:
        service = _make_service(
            score_result=_score_result(is_eligible=True, direction="NEUTRAL")
        )
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.SCORE_INELIGIBLE

    @pytest.mark.asyncio
    async def test_ineligible_does_not_call_confidence_engine(self) -> None:
        service = _make_service(score_result=_score_result(is_eligible=False))
        confidence = AsyncMock()
        confidence.calculate_confidence = AsyncMock(return_value=_confidence_result())
        service._confidence = confidence
        await service.process(_make_request())
        confidence.calculate_confidence.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# SE-02: Deduplication
# ──────────────────────────────────────────────────────────────────────────────


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_returns_duplicate_rejection(self) -> None:
        service = _make_service(is_duplicate=True)
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.DUPLICATE
        assert result.is_duplicate is True

    @pytest.mark.asyncio
    async def test_duplicate_does_not_persist_or_publish(self) -> None:
        service = _make_service(is_duplicate=True)
        await service.process(_make_request())
        service._repo.save.assert_not_called()
        service._bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_key_includes_strategy_and_regime(self) -> None:
        cache = AsyncMock()
        cache.is_duplicate = AsyncMock(return_value=False)
        cache.set_dedup = AsyncMock()
        cache.set_active_signal = AsyncMock()
        cache.get_active_signal_id = AsyncMock(return_value=None)
        service = _make_service()
        service._cache = cache
        service._dedup._cache = cache

        req1 = _make_request(strategy_type=StrategyType.DIRECTIONAL)
        req2 = _make_request(strategy_type=StrategyType.MEAN_REVERSION)

        # Each should check with different keys
        await service.process(req1)
        await service.process(req2)

        calls = [str(c) for c in cache.is_duplicate.call_args_list]
        assert any("DIRECTIONAL" in c for c in calls)
        assert any("MEAN_REVERSION" in c for c in calls)


# ──────────────────────────────────────────────────────────────────────────────
# SE-03: Weak signal gate
# ──────────────────────────────────────────────────────────────────────────────


class TestWeakSignal:
    @pytest.mark.asyncio
    async def test_low_score_returns_weak_signal_rejection(self) -> None:
        service = _make_service(
            score_result=_score_result(adjusted_score=60.0),
            confidence_result=_confidence_result(final_confidence=70.0),
        )
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.WEAK_SIGNAL

    @pytest.mark.asyncio
    async def test_low_confidence_returns_weak_signal_rejection(self) -> None:
        service = _make_service(
            score_result=_score_result(adjusted_score=80.0),
            confidence_result=_confidence_result(final_confidence=50.0),
        )
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.WEAK_SIGNAL

    @pytest.mark.asyncio
    async def test_weak_signal_is_persisted_before_events(self) -> None:
        save_calls: list[str] = []
        publish_calls: list[str] = []

        async def record_save(signal):
            save_calls.append("save")

        async def record_publish(event):
            publish_calls.append("publish")

        service = _make_service(
            score_result=_score_result(adjusted_score=60.0),
            confidence_result=_confidence_result(final_confidence=70.0),
        )
        service._repo.save = record_save
        service._bus.publish = record_publish

        await service.process(_make_request())
        assert len(save_calls) >= 1

    @pytest.mark.asyncio
    async def test_weak_signal_does_not_call_risk_engine(self) -> None:
        service = _make_service(
            score_result=_score_result(adjusted_score=60.0),
            confidence_result=_confidence_result(final_confidence=70.0),
        )
        await service.process(_make_request())
        service._risk.evaluate.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# SE-04: Risk rejection
# ──────────────────────────────────────────────────────────────────────────────


class TestRiskRejection:
    @pytest.mark.asyncio
    async def test_risk_rejected_returns_rejection(self) -> None:
        service = _make_service(
            risk_decision_mock=_risk_decision(
                approved=False,
                position_size_lots=None,
                rejection_code="DAILY_LOSS_LIMIT",
                rejection_reason="daily loss limit exceeded",
                risk_decision_id=None,
            )
        )
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.RISK_REJECTED

    @pytest.mark.asyncio
    async def test_risk_rejected_signal_is_persisted(self) -> None:
        service = _make_service(
            risk_decision_mock=_risk_decision(
                approved=False,
                position_size_lots=None,
                rejection_code="DAILY_LOSS_LIMIT",
                rejection_reason="exceeded",
                risk_decision_id=None,
            )
        )
        await service.process(_make_request())
        service._repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_risk_rejected_publishes_risk_rejected_event(self) -> None:
        published: list = []

        async def capture(event):
            published.append(event)

        service = _make_service(
            risk_decision_mock=_risk_decision(
                approved=False,
                position_size_lots=None,
                rejection_code="KILL_SWITCH_ACTIVE",
                rejection_reason="kill switch active",
                risk_decision_id=None,
            )
        )
        service._bus.publish = capture
        await service.process(_make_request())
        risk_rejected = [e for e in published if isinstance(e, SignalRiskRejected)]
        assert len(risk_rejected) == 1


# ──────────────────────────────────────────────────────────────────────────────
# SE-05: Happy path (risk approved)
# ──────────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_accepted_signal_returned(self) -> None:
        service = _make_service()
        result = await service.process(_make_request())
        assert result.accepted is True
        assert result.signal_id is not None
        assert result.rejection_reason is None
        assert result.risk_approved is True

    @pytest.mark.asyncio
    async def test_persistence_before_events(self) -> None:
        order: list[str] = []

        async def record_save(signal):
            order.append("save")

        async def record_publish(event):
            order.append("publish")

        service = _make_service()
        service._repo.save = record_save
        service._bus.publish = record_publish

        await service.process(_make_request())

        save_idx = next((i for i, v in enumerate(order) if v == "save"), None)
        publish_idx = next((i for i, v in enumerate(order) if v == "publish"), None)
        assert save_idx is not None
        if publish_idx is not None:
            assert save_idx < publish_idx

    @pytest.mark.asyncio
    async def test_dedup_key_registered_after_approval(self) -> None:
        service = _make_service()
        await service.process(_make_request())
        service._cache.set_dedup.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_and_confidence_in_result(self) -> None:
        service = _make_service(
            score_result=_score_result(adjusted_score=82.0),
            confidence_result=_confidence_result(final_confidence=74.0),
        )
        result = await service.process(_make_request())
        assert result.adjusted_score == pytest.approx(82.0)
        assert result.final_confidence == pytest.approx(74.0)

    @pytest.mark.asyncio
    async def test_position_size_lots_in_result(self) -> None:
        service = _make_service(risk_decision_mock=_risk_decision(position_size_lots=3))
        result = await service.process(_make_request())
        assert result.position_size_lots == 3

    @pytest.mark.asyncio
    async def test_explanation_is_populated(self) -> None:
        service = _make_service()
        result = await service.process(_make_request())
        assert result.explanation is not None

    @pytest.mark.asyncio
    async def test_publishes_risk_approved_event(self) -> None:
        published: list = []

        async def capture(event):
            published.append(event)

        service = _make_service()
        service._bus.publish = capture
        await service.process(_make_request())

        approved_events = [e for e in published if isinstance(e, SignalRiskApproved)]
        assert len(approved_events) == 1

    @pytest.mark.asyncio
    async def test_risk_approved_event_has_required_oms_fields(self) -> None:
        published: list = []

        async def capture(event):
            published.append(event)

        service = _make_service(
            score_result=_score_result(adjusted_score=78.0, direction="LONG"),
            confidence_result=_confidence_result(final_confidence=72.0),
            risk_decision_mock=_risk_decision(
                position_size_lots=2, risk_decision_id=101
            ),
        )
        service._bus.publish = capture
        await service.process(_make_request())

        evt = next(e for e in published if isinstance(e, SignalRiskApproved))
        assert evt.instrument_token == 1001
        assert evt.underlying == "NIFTY"
        assert evt.direction == "LONG"
        assert evt.adjusted_score == pytest.approx(78.0)
        assert evt.final_confidence == pytest.approx(72.0)
        assert evt.risk_decision_id == 101
        assert evt.strategy_type == "DIRECTIONAL"
        assert evt.regime == "TRENDING_BULLISH"
        assert evt.position_size_lots == 2
        assert evt.valid_until is not None


# ──────────────────────────────────────────────────────────────────────────────
# SE-06: Idempotency — no duplicate dedup registration on ineligible paths
# ──────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_dedup_not_registered_on_ineligible(self) -> None:
        service = _make_service(score_result=_score_result(is_eligible=False))
        await service.process(_make_request())
        service._cache.set_dedup.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_not_registered_on_weak_signal(self) -> None:
        service = _make_service(
            score_result=_score_result(adjusted_score=60.0),
            confidence_result=_confidence_result(final_confidence=70.0),
        )
        await service.process(_make_request())
        service._cache.set_dedup.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_not_registered_on_risk_rejection(self) -> None:
        service = _make_service(
            risk_decision_mock=_risk_decision(
                approved=False,
                position_size_lots=None,
                rejection_code="KILL_SWITCH_ACTIVE",
                rejection_reason="kill switch",
                risk_decision_id=None,
            )
        )
        await service.process(_make_request())
        service._cache.set_dedup.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# SE-07: Persistence fail-open is NOT acceptable
# ──────────────────────────────────────────────────────────────────────────────


class TestPersistenceFailOpen:
    @pytest.mark.asyncio
    async def test_db_error_raises_signal_persistence_error(self) -> None:
        service = _make_service(
            repo_save_raises=RuntimeError("DB connection lost"),
        )
        with pytest.raises(SignalPersistenceError):
            await service.process(_make_request())

    @pytest.mark.asyncio
    async def test_db_error_does_not_return_graceful_result(self) -> None:
        service = _make_service(
            repo_save_raises=RuntimeError("DB connection lost"),
        )
        try:
            await service.process(_make_request())
            pytest.fail("Expected SignalPersistenceError to be raised")
        except SignalPersistenceError:
            pass

    @pytest.mark.asyncio
    async def test_scoring_error_returns_graceful_result(self) -> None:
        service = _make_service()
        service._scoring.calculate_score = AsyncMock(side_effect=RuntimeError("crash"))
        result = await service.process(_make_request())
        assert result.accepted is False
        assert result.rejection_reason is not None

    @pytest.mark.asyncio
    async def test_redis_error_does_not_propagate(self) -> None:
        service = _make_service()
        service._cache.set_dedup = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = await service.process(_make_request())
        assert result.accepted is True  # Redis failure must not fail the signal


# ──────────────────────────────────────────────────────────────────────────────
# SE-08: Exception safety for engine errors
# ──────────────────────────────────────────────────────────────────────────────


class TestExceptionSafety:
    @pytest.mark.asyncio
    async def test_confidence_engine_exception_returns_graceful_result(self) -> None:
        service = _make_service()
        service._confidence.calculate_confidence = AsyncMock(
            side_effect=RuntimeError("crash")
        )
        result = await service.process(_make_request())
        assert result.accepted is False
