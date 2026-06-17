"""Unit tests for ConfidenceResult."""

from __future__ import annotations

import pytest

from core.domain.value_objects.confidence_result import ConfidenceResult


def _sha256() -> str:
    return "a" * 64


def _result(**kwargs: object) -> ConfidenceResult:
    defaults: dict[str, object] = {
        "base_confidence": 42.0,
        "win_rate_adj": 5.0,
        "regime_alignment_adj": 8.0,
        "data_quality_adj": 0.0,
        "momentum_adj": 0.0,
        "breakout_adj": 0.0,
        "loss_streak_adj": 0.0,
        "historical_accuracy_adj": 4.0,
        "signal_agreement_adj": 2.0,
        "recent_performance_adj": 0.0,
        "raw_confidence": 61.0,
        "calibrated_confidence": 61.0,
        "final_confidence": 61.0,
        "passed_gate": False,
        "score_bucket": "STANDARD",
        "fingerprint": _sha256(),
        "confidence_components": {"base_confidence": 42.0},
        "explanation": [],
    }
    defaults.update(kwargs)
    return ConfidenceResult(**defaults)  # type: ignore[arg-type]


class TestConfidenceResultValidation:
    def test_valid_construction(self) -> None:
        r = _result()
        assert r.final_confidence == 61.0

    def test_base_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            _result(base_confidence=101.0)

    def test_raw_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            _result(raw_confidence=-1.0)

    def test_final_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            _result(final_confidence=101.0)

    def test_invalid_score_bucket_raises(self) -> None:
        with pytest.raises(ValueError, match="score_bucket"):
            _result(score_bucket="WEAK")

    def test_short_fingerprint_raises(self) -> None:
        with pytest.raises(ValueError, match="fingerprint"):
            _result(fingerprint="abc")

    def test_frozen(self) -> None:
        r = _result()
        with pytest.raises((AttributeError, TypeError)):
            r.final_confidence = 99.0  # type: ignore[misc]

    def test_passed_gate_true_when_high_confidence(self) -> None:
        r = _result(
            final_confidence=70.0,
            calibrated_confidence=70.0,
            raw_confidence=70.0,
            passed_gate=True,
        )
        assert r.passed_gate is True

    def test_zero_confidence_valid(self) -> None:
        r = _result(
            raw_confidence=0.0,
            calibrated_confidence=0.0,
            final_confidence=0.0,
            passed_gate=False,
        )
        assert r.final_confidence == 0.0

    def test_signal_agreement_adj_stored(self) -> None:
        r = _result(signal_agreement_adj=5.0)
        assert r.signal_agreement_adj == 5.0

    def test_recent_performance_adj_stored(self) -> None:
        r = _result(recent_performance_adj=-6.0)
        assert r.recent_performance_adj == -6.0

    def test_explanation_defaults_to_empty_list(self) -> None:
        r = _result()
        assert r.explanation == []

    def test_explanation_stored_when_provided(self) -> None:
        lines = ["confidence=75.0 | direction=LONG | bucket=STANDARD | gate=PASS"]
        r = _result(explanation=lines)
        assert r.explanation == lines

    def test_confidence_components_can_include_sub_inputs(self) -> None:
        components = {
            "base_confidence": 42.0,
            "signal_agreement_adj": 2.0,
            "recent_performance_adj": 0.0,
            "dq_composite": 88.0,
            "sa_pct": 85.7,
        }
        r = _result(confidence_components=components)
        assert "dq_composite" in r.confidence_components
        assert "sa_pct" in r.confidence_components
