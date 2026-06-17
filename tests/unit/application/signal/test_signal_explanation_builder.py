"""Unit tests for SignalExplanationBuilder."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.application.services.signal.signal_explanation_builder import (
    SignalExplanationBuilder,
)
from core.domain.value_objects.signal_explanation import SignalExplanation


def _make_score_result(
    explanation: list[str] | None = None,
    direction: str = "LONG",
    adjusted_score: float = 78.0,
    score_quality: str = "HIGH",
    data_completeness_pct: float = 100.0,
) -> MagicMock:
    r = MagicMock()
    r.explanation = explanation or ["strong OI buildup", "EMA aligned"]
    r.direction = direction
    r.adjusted_score = adjusted_score
    r.score_quality = score_quality
    r.data_completeness_pct = data_completeness_pct
    return r


def _make_confidence_result(
    explanation: list[str] | None = None,
    final_confidence: float = 72.0,
    score_bucket: str = "STANDARD",
    passed_gate: bool = True,
) -> MagicMock:
    r = MagicMock()
    r.explanation = explanation or ["win_rate: 0.55", "regime: aligned"]
    r.final_confidence = final_confidence
    r.score_bucket = score_bucket
    r.passed_gate = passed_gate
    return r


def _make_risk_decision(
    approved: bool = True,
    checks: list | None = None,
    position_size_lots: int | None = 2,
    rejection_code: str | None = None,
    rejection_reason: str | None = None,
) -> MagicMock:
    r = MagicMock()
    r.approved = approved
    r.checks = checks or []
    r.position_size_lots = position_size_lots
    r.rejection_code = rejection_code
    r.rejection_reason = rejection_reason
    return r


class TestSignalExplanationBuilder:
    def test_build_with_no_inputs_returns_empty(self) -> None:
        builder = SignalExplanationBuilder()
        result = builder.build()
        assert result.is_empty
        assert result.rejection_reason is None

    def test_build_with_score_only(self) -> None:
        builder = SignalExplanationBuilder()
        score = _make_score_result()
        result = builder.build(score_result=score)
        assert len(result.score_lines) > 0
        assert result.confidence_lines == ()
        assert result.risk_lines == ()

    def test_score_lines_include_direction_and_score(self) -> None:
        builder = SignalExplanationBuilder()
        score = _make_score_result(direction="SHORT", adjusted_score=81.5)
        result = builder.build(score_result=score)
        combined = " ".join(result.score_lines)
        assert "SHORT" in combined
        assert "81.5" in combined

    def test_build_with_confidence(self) -> None:
        builder = SignalExplanationBuilder()
        score = _make_score_result()
        conf = _make_confidence_result()
        result = builder.build(score_result=score, confidence_result=conf)
        assert len(result.confidence_lines) > 0

    def test_confidence_lines_include_gate_status(self) -> None:
        builder = SignalExplanationBuilder()
        conf = _make_confidence_result(passed_gate=True)
        result = builder.build(confidence_result=conf)
        combined = " ".join(result.confidence_lines)
        assert "PASSED" in combined

    def test_build_with_risk_approved(self) -> None:
        builder = SignalExplanationBuilder()
        risk = _make_risk_decision(approved=True, position_size_lots=3)
        result = builder.build(risk_decision=risk)
        combined = " ".join(result.risk_lines)
        assert "APPROVED" in combined
        assert "3" in combined

    def test_build_with_risk_rejected(self) -> None:
        builder = SignalExplanationBuilder()
        risk = _make_risk_decision(
            approved=False,
            position_size_lots=None,
            rejection_code="DAILY_LOSS_LIMIT",
            rejection_reason="daily loss limit exceeded",
        )
        result = builder.build(risk_decision=risk, rejection_reason="RISK_REJECTED")
        combined = " ".join(result.risk_lines)
        assert "REJECTED" in combined

    def test_rejection_reason_propagated(self) -> None:
        builder = SignalExplanationBuilder()
        result = builder.build(rejection_reason="weak_signal")
        assert result.rejection_reason == "weak_signal"

    def test_returns_signal_explanation_type(self) -> None:
        builder = SignalExplanationBuilder()
        result = builder.build()
        assert isinstance(result, SignalExplanation)
