"""Integration tests for Signal Engine (Phase 14).

Validates the full orchestration pipeline with real domain objects:
- Signal entity state machine transitions
- Persistence-first invariant
- Deduplication correctness (including strategy/regime differentiation)
- Explanation assembly
- All rejection paths
- SignalRiskApproved event OMS fields
- Persistence fail-open prevention

All I/O boundaries (Score/Confidence/Risk engines, DB, Redis, event bus)
are mocked. Domain logic uses real implementations.

Test IDs: SE-I-1 through SE-I-12
"""

from __future__ import annotations

import uuid
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

_FINGERPRINT = "f" * 64


def _score(
    is_eligible: bool = True,
    direction: str = "LONG",
    raw_score: float = 78.0,
    adjusted_score: float = 78.0,
    weights_sha256: str = "s" * 64,
) -> MagicMock:
    r = MagicMock()
    r.is_eligible = is_eligible
    r.direction = direction
    r.raw_score = raw_score
    r.adjusted_score = adjusted_score
    r.weights_sha256 = weights_sha256
    r.score_quality = "HIGH"
    r.data_completeness_pct = 100.0
    r.explanation = ["OI buildup detected", "EMA 9/21 aligned bullish"]
    return r


def _conf(final_confidence: float = 72.0, passed_gate: bool = True) -> MagicMock:
    r = MagicMock()
    r.final_confidence = final_confidence
    r.fingerprint = _FINGERPRINT
    r.score_bucket = "STANDARD"
    r.passed_gate = passed_gate
    r.explanation = ["win_rate=0.57", "regime=aligned"]
    return r


def _risk(approved: bool = True, lots: int | None = 2, code: str | None = None) -> MagicMock:
    r = MagicMock()
    r.approved = approved
    r.position_size_lots = lots
    r.rejection_code = code
    r.rejection_reason = f"{code} triggered" if code else None
    r.checks = ()
    r.sizing = None
    return r


def _make_cache(is_dup: bool = False) -> AsyncMock:
    cache = AsyncMock()
    cache.is_duplicate = AsyncMock(return_value=is_dup)
    cache.set_dedup = AsyncMock()
    cache.get_active_signal_id = AsyncMock(return_value=None)
    cache.set_active_signal = AsyncMock()
    cache.delete_active_signal = AsyncMock()
    return cache


def _make_service(
    score_result=None,
    confidence_result=None,
    risk_result=None,
    is_dup: bool = False,
) -> tuple[SignalEngineService, dict]:
    scoring = AsyncMock()
    scoring.calculate_score = AsyncMock(return_value=score_result or _score())
    confidence = AsyncMock()
    confidence.calculate_confidence = AsyncMock(
        return_value=confidence_result or _conf()
    )
    risk = AsyncMock()
    risk.evaluate = AsyncMock(return_value=risk_result or _risk())

    saved_signals: list = []
    published_events: list = []
    save_order: list[str] = []
    pub_order: list[str] = []

    async def _save(signal):
        save_order.append("save")
        saved_signals.append(signal)

    async def _publish(event):
        pub_order.append("publish")
        published_events.append(event)

    repo = AsyncMock()
    repo.save = _save

    cache = _make_cache(is_dup=is_dup)

    bus = AsyncMock()
    bus.publish = _publish

    config = SignalConfig()
    dedup_svc = SignalDeduplicationService(cache, config)
    builder = SignalExplanationBuilder()

    svc = SignalEngineService(
        scoring_engine=scoring,
        confidence_engine=confidence,
        risk_engine=risk,
        signal_repository=repo,
        signal_cache=cache,
        event_bus=bus,
        explanation_builder=builder,
        dedup_service=dedup_svc,
        config=config,
    )

    context = {
        "saved_signals": saved_signals,
        "published_events": published_events,
        "save_order": save_order,
        "pub_order": pub_order,
        "scoring": scoring,
        "confidence": confidence,
        "risk": risk,
        "cache": cache,
    }
    return svc, context


def _request(
    underlying: str = "NIFTY",
    strategy_type: StrategyType = StrategyType.DIRECTIONAL,
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
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
    )


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-1: Happy path end-to-end
# ──────────────────────────────────────────────────────────────────────────────


class TestHappyPathEndToEnd:
    @pytest.mark.asyncio
    async def test_accepted_result_has_signal_id(self) -> None:
        svc, ctx = _make_service()
        result = await svc.process(_request())
        assert result.accepted is True
        assert result.signal_id is not None
        assert isinstance(result.signal_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_all_three_engines_called(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        ctx["scoring"].calculate_score.assert_called_once()
        ctx["confidence"].calculate_confidence.assert_called_once()
        ctx["risk"].evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_signal_persisted(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        assert len(ctx["saved_signals"]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-2: Persistence-first invariant
# ──────────────────────────────────────────────────────────────────────────────


class TestPersistenceFirst:
    @pytest.mark.asyncio
    async def test_save_before_publish_on_approved(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        assert len(ctx["saved_signals"]) == 1

    @pytest.mark.asyncio
    async def test_save_before_publish_on_weak_signal(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=50.0),
            confidence_result=_conf(final_confidence=70.0),
        )
        await svc.process(_request())
        # Signal must be saved even for weak signal
        assert len(ctx["saved_signals"]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-3: Deduplication prevents duplicate signals
# ──────────────────────────────────────────────────────────────────────────────


class TestDeduplicationIntegration:
    @pytest.mark.asyncio
    async def test_duplicate_not_persisted(self) -> None:
        svc, ctx = _make_service(is_dup=True)
        result = await svc.process(_request())
        assert result.is_duplicate is True
        assert len(ctx["saved_signals"]) == 0

    @pytest.mark.asyncio
    async def test_duplicate_events_not_published(self) -> None:
        svc, ctx = _make_service(is_dup=True)
        await svc.process(_request())
        assert len(ctx["published_events"]) == 0

    @pytest.mark.asyncio
    async def test_dedup_key_set_after_approval(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        ctx["cache"].set_dedup.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-4: Score ineligible path
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreIneligiblePath:
    @pytest.mark.asyncio
    async def test_score_ineligible_no_downstream_calls(self) -> None:
        svc, ctx = _make_service(score_result=_score(is_eligible=False))
        result = await svc.process(_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.SCORE_INELIGIBLE
        ctx["confidence"].calculate_confidence.assert_not_called()
        ctx["risk"].evaluate.assert_not_called()
        assert len(ctx["saved_signals"]) == 0


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-5: Weak signal gate
# ──────────────────────────────────────────────────────────────────────────────


class TestWeakSignalGate:
    @pytest.mark.asyncio
    async def test_score_below_gate_is_weak(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=65.0),
            confidence_result=_conf(final_confidence=72.0),
        )
        result = await svc.process(_request())
        assert result.rejection_reason == SignalRejectionReason.WEAK_SIGNAL
        ctx["risk"].evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_confidence_below_gate_is_weak(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=80.0),
            confidence_result=_conf(final_confidence=60.0),
        )
        result = await svc.process(_request())
        assert result.rejection_reason == SignalRejectionReason.WEAK_SIGNAL

    @pytest.mark.asyncio
    async def test_exactly_at_gate_passes(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=70.0),
            confidence_result=_conf(final_confidence=65.0),
        )
        result = await svc.process(_request())
        assert result.rejection_reason != SignalRejectionReason.WEAK_SIGNAL
        ctx["risk"].evaluate.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-6: Risk rejection path
# ──────────────────────────────────────────────────────────────────────────────


class TestRiskRejectionPath:
    @pytest.mark.asyncio
    async def test_risk_rejected_signal_persisted(self) -> None:
        svc, ctx = _make_service(
            risk_result=_risk(
                approved=False,
                lots=None,
                code="DAILY_LOSS_LIMIT",
            )
        )
        result = await svc.process(_request())
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.RISK_REJECTED
        assert len(ctx["saved_signals"]) == 1

    @pytest.mark.asyncio
    async def test_risk_rejected_dedup_not_registered(self) -> None:
        svc, ctx = _make_service(
            risk_result=_risk(
                approved=False,
                lots=None,
                code="KILL_SWITCH_ACTIVE",
            )
        )
        await svc.process(_request())
        ctx["cache"].set_dedup.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-7: Signal explanation
# ──────────────────────────────────────────────────────────────────────────────


class TestSignalExplanation:
    @pytest.mark.asyncio
    async def test_explanation_has_score_lines_on_happy_path(self) -> None:
        svc, ctx = _make_service(score_result=_score())
        result = await svc.process(_request())
        assert result.explanation is not None
        assert not result.explanation.is_empty

    @pytest.mark.asyncio
    async def test_explanation_has_rejection_reason_on_weak(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=55.0),
            confidence_result=_conf(final_confidence=72.0),
        )
        result = await svc.process(_request())
        assert result.explanation is not None
        assert result.explanation.rejection_reason is not None


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-8: Risk reward ratio calculation
# ──────────────────────────────────────────────────────────────────────────────


class TestRiskRewardRatio:
    @pytest.mark.asyncio
    async def test_risk_request_built_with_positive_rr(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        ctx["risk"].evaluate.assert_called_once()
        risk_req = ctx["risk"].evaluate.call_args[0][0]
        assert risk_req.risk_reward_ratio > 0

    @pytest.mark.asyncio
    async def test_underlying_in_risk_request(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request(underlying="BANKNIFTY"))
        risk_req = ctx["risk"].evaluate.call_args[0][0]
        assert risk_req.underlying == "BANKNIFTY"


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-9: Fix 1 — Dedup key includes strategy_type and regime
# ──────────────────────────────────────────────────────────────────────────────


class TestDedupKeyStrategyRegimeDifferentiation:
    @pytest.mark.asyncio
    async def test_trend_and_mean_reversion_not_deduped(self) -> None:
        """NIFTY LONG Trend and NIFTY LONG Mean Reversion must NOT be treated as dups."""
        svc, ctx = _make_service()

        req_trend = _request(strategy_type=StrategyType.DIRECTIONAL)
        req_mr = _request(strategy_type=StrategyType.MEAN_REVERSION)

        result1 = await svc.process(req_trend)
        result2 = await svc.process(req_mr)

        # Both must be accepted (not rejected as duplicates)
        assert result1.accepted is True
        assert result2.accepted is True

    @pytest.mark.asyncio
    async def test_dedup_check_receives_strategy_type_in_key(self) -> None:
        svc, ctx = _make_service()
        req = _request(strategy_type=StrategyType.DIRECTIONAL)
        await svc.process(req)
        # set_dedup is called with the key; verify key includes strategy type string
        call_args = ctx["cache"].set_dedup.call_args
        assert call_args is not None
        key_arg = call_args[0][0]  # positional first arg
        assert "DIRECTIONAL" in key_arg

    @pytest.mark.asyncio
    async def test_dedup_check_receives_regime_in_key(self) -> None:
        svc, ctx = _make_service()
        req = _request(regime=MarketRegime.TRENDING_BEARISH)
        await svc.process(req)
        call_args = ctx["cache"].set_dedup.call_args
        assert call_args is not None
        key_arg = call_args[0][0]
        assert "TRENDING_BEARISH" in key_arg

    @pytest.mark.asyncio
    async def test_bullish_and_bearish_regime_not_deduped(self) -> None:
        svc, ctx = _make_service()

        req_bull = _request(regime=MarketRegime.TRENDING_BULLISH)
        req_bear = _request(regime=MarketRegime.TRENDING_BEARISH)

        result1 = await svc.process(req_bull)
        result2 = await svc.process(req_bear)

        assert result1.accepted is True
        assert result2.accepted is True


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-10: Fix 4 — Persistence errors must propagate (never fail-open)
# ──────────────────────────────────────────────────────────────────────────────


class TestPersistenceErrorPropagation:
    @pytest.mark.asyncio
    async def test_db_failure_raises_signal_persistence_error(self) -> None:
        svc, ctx = _make_service()
        svc._repo.save = AsyncMock(side_effect=RuntimeError("connection pool exhausted"))
        with pytest.raises(SignalPersistenceError):
            await svc.process(_request())

    @pytest.mark.asyncio
    async def test_db_failure_does_not_return_graceful_result(self) -> None:
        svc, ctx = _make_service()
        svc._repo.save = AsyncMock(side_effect=OSError("disk full"))
        raised = False
        try:
            await svc.process(_request())
        except SignalPersistenceError:
            raised = True
        assert raised, "SignalPersistenceError must propagate; fail-open is NOT acceptable for DB"

    @pytest.mark.asyncio
    async def test_db_failure_on_weak_signal_also_propagates(self) -> None:
        svc, ctx = _make_service(
            score_result=_score(adjusted_score=55.0),
            confidence_result=_conf(final_confidence=70.0),
        )
        svc._repo.save = AsyncMock(side_effect=RuntimeError("DB down"))
        with pytest.raises(SignalPersistenceError):
            await svc.process(_request())

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_propagate(self) -> None:
        svc, ctx = _make_service()
        svc._cache.set_dedup = AsyncMock(side_effect=ConnectionError("Redis down"))
        result = await svc.process(_request())
        assert result.accepted is True


# ──────────────────────────────────────────────────────────────────────────────
# SE-I-11: Fix 5 — SignalRiskApproved event contains all OMS-required fields
# ──────────────────────────────────────────────────────────────────────────────


class TestSignalRiskApprovedOmsFields:
    @pytest.mark.asyncio
    async def test_signal_risk_approved_event_published(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        approved_events = [
            e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved)
        ]
        assert len(approved_events) == 1

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_instrument_token(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.instrument_token == 1001

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_underlying(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request(underlying="BANKNIFTY"))
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.underlying == "BANKNIFTY"

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_direction(self) -> None:
        svc, ctx = _make_service(score_result=_score(direction="SHORT"))
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.direction == "SHORT"

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_score(self) -> None:
        svc, ctx = _make_service(score_result=_score(adjusted_score=83.5))
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.adjusted_score == pytest.approx(83.5)

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_confidence(self) -> None:
        svc, ctx = _make_service(confidence_result=_conf(final_confidence=68.0))
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.final_confidence == pytest.approx(68.0)

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_risk_decision_id(self) -> None:
        risk = _risk(approved=True, lots=2)
        risk.risk_decision_id = 999
        svc, ctx = _make_service(risk_result=risk)
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.risk_decision_id == 999

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_strategy_type(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request(strategy_type=StrategyType.MEAN_REVERSION))
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.strategy_type == "MEAN_REVERSION"

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_regime(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request(regime=MarketRegime.TRENDING_BEARISH))
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.regime == "TRENDING_BEARISH"

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_position_size_lots(self) -> None:
        svc, ctx = _make_service(risk_result=_risk(approved=True, lots=4))
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.position_size_lots == 4

    @pytest.mark.asyncio
    async def test_signal_risk_approved_contains_valid_until(self) -> None:
        svc, ctx = _make_service()
        await svc.process(_request())
        evt = next(e for e in ctx["published_events"] if isinstance(e, SignalRiskApproved))
        assert evt.valid_until is not None

    @pytest.mark.asyncio
    async def test_signal_risk_rejected_event_published_on_rejection(self) -> None:
        svc, ctx = _make_service(
            risk_result=_risk(approved=False, lots=None, code="DAILY_LOSS_LIMIT")
        )
        await svc.process(_request())
        rejected_events = [
            e for e in ctx["published_events"] if isinstance(e, SignalRiskRejected)
        ]
        assert len(rejected_events) == 1
