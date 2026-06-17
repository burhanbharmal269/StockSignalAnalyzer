"""Unit tests for Signal entity state machine — every valid and invalid transition tested."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.domain.entities.signal import Signal
from core.domain.enums.asset_type import AssetType
from core.domain.enums.market_regime import MarketRegime
from core.domain.enums.signal_state import SignalState
from core.domain.enums.signal_type import SignalType
from core.domain.enums.strategy_type import StrategyType
from core.domain.exceptions.signal import SignalStateError
from core.domain.value_objects.confidence import Confidence
from core.domain.value_objects.score import Score
from core.domain.value_objects.symbol import Symbol


def _make_signal(state: SignalState = SignalState.PENDING) -> Signal:
    sig = Signal.create(
        symbol=Symbol("NIFTY"),
        signal_type=SignalType.LONG,
        strategy_type=StrategyType.DIRECTIONAL,
        asset_type=AssetType.FNO,
        regime=MarketRegime.TRENDING_BULLISH,
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
    )
    sig.state = state
    return sig


def _scored_signal(score: int = 82, conf: int = 75) -> Signal:
    """Return a signal in SCORED state."""
    sig = _make_signal(SignalState.SCORING)
    sig.complete_scoring(
        raw_score=Score(80),
        adjusted_score=Score(score),
        confidence=Confidence(conf),
        scoring_weights_sha256="abc123",
    )
    return sig


def _risk_pending_signal() -> Signal:
    sig = _scored_signal()
    sig.submit_to_risk(min_score=70, min_confidence=65)
    return sig


def _risk_approved_signal() -> Signal:
    sig = _risk_pending_signal()
    sig.approve_risk()
    return sig


def _forwarded_signal() -> Signal:
    sig = _risk_approved_signal()
    sig.forward_to_oms()
    return sig


class TestSignalFactory:
    def test_create_sets_pending_state(self) -> None:
        sig = Signal.create(
            symbol=Symbol("NIFTY"),
            signal_type=SignalType.LONG,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BULLISH,
            valid_until=datetime.now(UTC) + timedelta(minutes=30),
        )
        assert sig.state == SignalState.PENDING

    def test_create_assigns_unique_ids(self) -> None:
        s1 = Signal.create(
            symbol=Symbol("NIFTY"),
            signal_type=SignalType.LONG,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BULLISH,
            valid_until=datetime.now(UTC) + timedelta(minutes=30),
        )
        s2 = Signal.create(
            symbol=Symbol("NIFTY"),
            signal_type=SignalType.LONG,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BULLISH,
            valid_until=datetime.now(UTC) + timedelta(minutes=30),
        )
        assert s1.signal_id != s2.signal_id


class TestValidTransitions:
    def test_pending_to_scoring(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        sig.start_scoring()
        assert sig.state == SignalState.SCORING

    def test_scoring_to_scored(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        sig.complete_scoring(Score(80), Score(82), Confidence(75), "sha256")
        assert sig.state == SignalState.SCORED

    def test_scored_to_risk_pending_passes_gate(self) -> None:
        sig = _scored_signal(score=82, conf=75)
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.RISK_PENDING

    def test_scored_to_weak_signal_fails_score_gate(self) -> None:
        sig = _scored_signal(score=69, conf=75)
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.WEAK_SIGNAL

    def test_scored_to_weak_signal_fails_confidence_gate(self) -> None:
        sig = _scored_signal(score=82, conf=64)
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.WEAK_SIGNAL

    def test_scored_to_weak_signal_both_fail(self) -> None:
        sig = _scored_signal(score=50, conf=40)
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.WEAK_SIGNAL

    def test_exactly_at_gate_boundary_passes(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        sig.complete_scoring(Score(70), Score(70), Confidence(65), "sha256")
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.RISK_PENDING

    def test_scored_to_risk_pending(self) -> None:
        sig = _scored_signal()
        sig.submit_to_risk(min_score=70, min_confidence=65)
        assert sig.state == SignalState.RISK_PENDING

    def test_risk_pending_to_approved(self) -> None:
        sig = _risk_pending_signal()
        sig.approve_risk()
        assert sig.state == SignalState.RISK_APPROVED

    def test_risk_pending_to_rejected(self) -> None:
        sig = _risk_pending_signal()
        sig.reject_risk("daily loss limit")
        assert sig.state == SignalState.RISK_REJECTED
        assert sig.risk_rejection_reason == "daily loss limit"

    def test_risk_approved_to_forwarded(self) -> None:
        sig = _risk_approved_signal()
        sig.forward_to_oms()
        assert sig.state == SignalState.FORWARDED

    def test_forwarded_to_executed(self) -> None:
        sig = _forwarded_signal()
        sig.mark_executed()
        assert sig.state == SignalState.EXECUTED

    def test_forwarded_to_expired(self) -> None:
        sig = _forwarded_signal()
        sig.expire()
        assert sig.state == SignalState.EXPIRED

    def test_forwarded_to_cancelled(self) -> None:
        sig = _forwarded_signal()
        sig.cancel()
        assert sig.state == SignalState.CANCELLED

    def test_pending_to_cancelled(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        sig.cancel()
        assert sig.state == SignalState.CANCELLED

    def test_scoring_to_cancelled(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        sig.cancel()
        assert sig.state == SignalState.CANCELLED

    def test_scored_to_cancelled(self) -> None:
        sig = _scored_signal()
        sig.cancel()
        assert sig.state == SignalState.CANCELLED

    def test_pending_to_failed(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        sig.fail()
        assert sig.state == SignalState.FAILED

    def test_scoring_to_failed(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        sig.fail()
        assert sig.state == SignalState.FAILED

    def test_risk_pending_to_failed(self) -> None:
        sig = _risk_pending_signal()
        sig.fail()
        assert sig.state == SignalState.FAILED

    def test_forwarded_to_failed(self) -> None:
        sig = _forwarded_signal()
        sig.fail()
        assert sig.state == SignalState.FAILED


class TestInvalidTransitions:
    def test_pending_cannot_jump_to_scored(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        with pytest.raises(SignalStateError):
            sig._transition_to(SignalState.SCORED)

    def test_pending_cannot_jump_to_executed(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        with pytest.raises(SignalStateError):
            sig.mark_executed()

    def test_scoring_cannot_go_to_risk_pending(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        with pytest.raises(SignalStateError):
            sig.submit_to_risk(min_score=70, min_confidence=65)

    def test_weak_signal_is_terminal(self) -> None:
        sig = _make_signal(SignalState.WEAK_SIGNAL)
        with pytest.raises(SignalStateError):
            sig.start_scoring()

    def test_executed_is_terminal(self) -> None:
        sig = _make_signal(SignalState.EXECUTED)
        with pytest.raises(SignalStateError):
            sig.expire()

    def test_risk_rejected_is_terminal(self) -> None:
        sig = _make_signal(SignalState.RISK_REJECTED)
        with pytest.raises(SignalStateError):
            sig.approve_risk()

    def test_cancelled_is_terminal(self) -> None:
        sig = _make_signal(SignalState.CANCELLED)
        with pytest.raises(SignalStateError):
            sig.start_scoring()

    def test_failed_is_terminal(self) -> None:
        sig = _make_signal(SignalState.FAILED)
        with pytest.raises(SignalStateError):
            sig.start_scoring()

    def test_risk_approved_cannot_skip_to_executed(self) -> None:
        sig = _risk_approved_signal()
        with pytest.raises(SignalStateError):
            sig.mark_executed()

    def test_forwarded_cannot_go_to_risk_pending(self) -> None:
        sig = _forwarded_signal()
        with pytest.raises(SignalStateError):
            sig.submit_to_risk(min_score=70, min_confidence=65)

    def test_expired_is_terminal(self) -> None:
        sig = _make_signal(SignalState.EXPIRED)
        with pytest.raises(SignalStateError):
            sig.mark_executed()


class TestSignalQueries:
    def test_passed_execution_gate_true(self) -> None:
        sig = _scored_signal()
        assert sig.passed_execution_gate(min_score=70, min_confidence=65) is True

    def test_passed_execution_gate_false_before_scoring(self) -> None:
        sig = _make_signal(SignalState.PENDING)
        assert sig.passed_execution_gate(min_score=70, min_confidence=65) is False

    def test_is_expired_by_ttl(self) -> None:
        sig = Signal.create(
            symbol=Symbol("NIFTY"),
            signal_type=SignalType.LONG,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BULLISH,
            valid_until=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert sig.is_expired_by_ttl is True

    def test_not_expired_by_ttl(self) -> None:
        sig = Signal.create(
            symbol=Symbol("NIFTY"),
            signal_type=SignalType.LONG,
            strategy_type=StrategyType.DIRECTIONAL,
            asset_type=AssetType.FNO,
            regime=MarketRegime.TRENDING_BULLISH,
            valid_until=datetime.now(UTC) + timedelta(minutes=30),
        )
        assert sig.is_expired_by_ttl is False

    def test_pull_events_drains_list(self) -> None:
        sig = _make_signal()
        sig._pending_events.append("event1")
        sig._pending_events.append("event2")
        events = sig.pull_events()
        assert len(events) == 2
        assert sig.pull_events() == []

    def test_complete_scoring_stores_sha256(self) -> None:
        sig = _make_signal(SignalState.SCORING)
        sig.complete_scoring(Score(80), Score(82), Confidence(75), "deadbeef")
        assert sig.scoring_weights_sha256 == "deadbeef"
