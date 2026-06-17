"""Unit tests for ScoreResult value object."""

from __future__ import annotations

import pytest

from core.domain.value_objects.score_breakdown import ScoreBreakdown
from core.domain.value_objects.score_penalty import ScorePenalty
from core.domain.value_objects.score_result import ScoreResult


def _breakdown(**kwargs) -> ScoreBreakdown:
    defaults = {
        "oi_buildup": 20.0,
        "trend": 15.0,
        "option_chain": 10.0,
        "volume": 8.0,
        "vwap": 5.0,
        "sentiment": 2.0,
        "iv_analysis": 2.0,
        "regime_alignment": "ALIGNED",
        "regime_mismatch": False,
        "total_before_penalties": 62.0,
    }
    defaults.update(kwargs)
    return ScoreBreakdown(**defaults)


def _result(**kwargs) -> ScoreResult:
    defaults = {
        "direction": "LONG",
        "direction_conviction": 0.75,
        "raw_score": 75.0,
        "adjusted_score": 67.0,
        "score_breakdown": _breakdown(),
        "penalties": [],
        "data_completeness_pct": 100.0,
        "is_eligible": True,
        "score_quality": "HIGH",
        "weights_sha256": "abc123",
    }
    defaults.update(kwargs)
    return ScoreResult(**defaults)


class TestScoreResultConstruction:
    def test_valid_long_result(self) -> None:
        r = _result(direction="LONG")
        assert r.direction == "LONG"
        assert r.is_eligible is True

    def test_valid_short_result(self) -> None:
        r = _result(direction="SHORT")
        assert r.direction == "SHORT"

    def test_valid_neutral_result(self) -> None:
        r = _result(direction="NEUTRAL", adjusted_score=0.0, raw_score=0.0, is_eligible=False)
        assert r.direction == "NEUTRAL"

    def test_is_frozen(self) -> None:
        r = _result()
        with pytest.raises((AttributeError, TypeError)):
            r.direction = "SHORT"  # type: ignore[misc]

    def test_evaluated_at_defaults_to_utc(self) -> None:
        r = _result()
        assert r.evaluated_at.tzinfo is not None

    def test_explanation_defaults_empty(self) -> None:
        r = _result()
        assert r.explanation == []


class TestScoreResultValidation:
    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            _result(direction="BUY")

    def test_conviction_above_1_raises(self) -> None:
        with pytest.raises(ValueError, match="conviction"):
            _result(direction_conviction=1.1)

    def test_conviction_below_0_raises(self) -> None:
        with pytest.raises(ValueError, match="conviction"):
            _result(direction_conviction=-0.1)

    def test_raw_score_above_100_raises(self) -> None:
        with pytest.raises(ValueError, match="raw_score"):
            _result(raw_score=101.0)

    def test_adjusted_score_below_0_raises(self) -> None:
        with pytest.raises(ValueError, match="adjusted_score"):
            _result(adjusted_score=-1.0)

    def test_invalid_quality_raises(self) -> None:
        with pytest.raises(ValueError, match="score_quality"):
            _result(score_quality="EXCELLENT")

    def test_all_quality_values_valid(self) -> None:
        for q in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT"):
            r = _result(score_quality=q)
            assert r.score_quality == q


class TestScoreResultProperties:
    def test_total_penalty_sums_amounts(self) -> None:
        penalties = [
            ScorePenalty("DATA_STALENESS", -10.0, "stale", "OI_BUILDUP"),
            ScorePenalty("REGIME_MISMATCH", -20.0, "opposed"),
        ]
        r = _result(penalties=penalties, adjusted_score=30.0)
        assert r.total_penalty == -30.0

    def test_total_penalty_zero_when_no_penalties(self) -> None:
        r = _result(penalties=[])
        assert r.total_penalty == 0.0
