"""Unit tests for SignalExplanation value object."""

from __future__ import annotations

import pytest

from core.domain.value_objects.signal_explanation import SignalExplanation


class TestSignalExplanation:
    def test_full_text_with_all_sections(self) -> None:
        exp = SignalExplanation(
            score_lines=("Score line 1", "Score line 2"),
            confidence_lines=("Confidence line 1",),
            risk_lines=("Risk line 1",),
        )
        text = exp.full_text
        assert "Score:" in text
        assert "Score line 1" in text
        assert "Confidence:" in text
        assert "Risk:" in text

    def test_rejection_reason_in_full_text(self) -> None:
        exp = SignalExplanation(
            score_lines=(),
            confidence_lines=(),
            risk_lines=(),
            rejection_reason="score_ineligible",
        )
        assert "score_ineligible" in exp.full_text

    def test_is_empty_true_when_no_lines(self) -> None:
        exp = SignalExplanation(
            score_lines=(),
            confidence_lines=(),
            risk_lines=(),
        )
        assert exp.is_empty is True

    def test_is_empty_false_with_score_lines(self) -> None:
        exp = SignalExplanation(
            score_lines=("a line",),
            confidence_lines=(),
            risk_lines=(),
        )
        assert exp.is_empty is False

    def test_frozen(self) -> None:
        exp = SignalExplanation(score_lines=(), confidence_lines=(), risk_lines=())
        with pytest.raises(Exception):
            exp.score_lines = ("new",)  # type: ignore[misc]

    def test_no_rejection_reason_by_default(self) -> None:
        exp = SignalExplanation(score_lines=(), confidence_lines=(), risk_lines=())
        assert exp.rejection_reason is None

    def test_empty_full_text_when_no_sections(self) -> None:
        exp = SignalExplanation(score_lines=(), confidence_lines=(), risk_lines=())
        assert exp.full_text == ""
