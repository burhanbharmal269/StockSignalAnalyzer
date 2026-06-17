"""Unit tests for SignalResult value object."""

from __future__ import annotations

import uuid

import pytest

from core.domain.enums.signal_rejection_reason import SignalRejectionReason
from core.domain.value_objects.signal_explanation import SignalExplanation
from core.domain.value_objects.signal_result import SignalResult


def _explanation() -> SignalExplanation:
    return SignalExplanation(score_lines=(), confidence_lines=(), risk_lines=())


class TestSignalResult:
    def test_accepted_result(self) -> None:
        sid = uuid.uuid4()
        result = SignalResult(
            accepted=True,
            signal_id=sid,
            rejection_reason=None,
            explanation=_explanation(),
            is_duplicate=False,
            adjusted_score=82.0,
            final_confidence=70.0,
            risk_approved=True,
            position_size_lots=2,
        )
        assert result.accepted is True
        assert result.signal_id == sid
        assert result.rejection_reason is None
        assert result.position_size_lots == 2

    def test_rejected_result(self) -> None:
        result = SignalResult(
            accepted=False,
            signal_id=None,
            rejection_reason=SignalRejectionReason.WEAK_SIGNAL,
            explanation=_explanation(),
            is_duplicate=False,
        )
        assert result.accepted is False
        assert result.rejection_reason == SignalRejectionReason.WEAK_SIGNAL
        assert result.signal_id is None

    def test_duplicate_result(self) -> None:
        result = SignalResult(
            accepted=False,
            signal_id=None,
            rejection_reason=SignalRejectionReason.DUPLICATE,
            explanation=_explanation(),
            is_duplicate=True,
        )
        assert result.is_duplicate is True
        assert result.accepted is False

    def test_frozen(self) -> None:
        result = SignalResult(
            accepted=False,
            signal_id=None,
            rejection_reason=SignalRejectionReason.DUPLICATE,
            explanation=_explanation(),
            is_duplicate=True,
        )
        with pytest.raises(Exception):
            result.accepted = True  # type: ignore[misc]

    def test_defaults(self) -> None:
        result = SignalResult(
            accepted=True,
            signal_id=uuid.uuid4(),
            rejection_reason=None,
            explanation=None,
            is_duplicate=False,
        )
        assert result.adjusted_score is None
        assert result.final_confidence is None
        assert result.risk_approved is False
        assert result.position_size_lots is None
