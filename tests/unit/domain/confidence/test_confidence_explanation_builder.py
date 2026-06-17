"""Unit tests for ConfidenceExplanationBuilder — pure domain service."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.domain.confidence.confidence_explanation_builder import ConfidenceExplanationBuilder
from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.confidence_result import ConfidenceResult
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_context import ScoreContext
from core.infrastructure.config.confidence_config import load_confidence_config

_cfg = load_confidence_config()
_builder = ConfidenceExplanationBuilder(_cfg)

_SHA = "a" * 64

_FORBIDDEN = {"BUY", "SELL", "ORDER", "TRADE", "ENTRY", "STOP_LOSS", "TARGET"}


def _make_context(regime: MarketRegime = MarketRegime.TRENDING_BULLISH) -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m", india_vix=16.0)
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features,
    )


def _make_score_result(direction: str = "LONG") -> MagicMock:
    mock = MagicMock()
    mock.direction = direction
    return mock


def _make_result(**kwargs: object) -> ConfidenceResult:
    components: dict[str, float] = {
        "base_confidence": 42.0,
        "win_rate_adj": 10.0,
        "regime_alignment_adj": 8.0,
        "data_quality_adj": 5.0,
        "momentum_adj": 0.0,
        "breakout_adj": 0.0,
        "loss_streak_adj": -6.0,
        "historical_accuracy_adj": 4.0,
        "signal_agreement_adj": 5.0,
        "recent_performance_adj": 2.0,
        "dq_score_quality_score": 100.0,
        "dq_completeness_score": 100.0,
        "dq_freshness_score": 100.0,
        "dq_composite": 100.0,
        "sa_agreeing": 7.0,
        "sa_available": 7.0,
        "sa_pct": 100.0,
        "rp_short_win_pct": 70.0,
        "rp_long_win_pct": 65.0,
        "rp_combined_pct": 68.5,
    }
    defaults: dict[str, object] = {
        "base_confidence": 42.0,
        "win_rate_adj": 10.0,
        "regime_alignment_adj": 8.0,
        "data_quality_adj": 5.0,
        "momentum_adj": 0.0,
        "breakout_adj": 0.0,
        "loss_streak_adj": -6.0,
        "historical_accuracy_adj": 4.0,
        "signal_agreement_adj": 5.0,
        "recent_performance_adj": 2.0,
        "raw_confidence": 70.0,
        "calibrated_confidence": 70.0,
        "final_confidence": 70.0,
        "passed_gate": True,
        "score_bucket": "STANDARD",
        "fingerprint": _SHA,
        "confidence_components": components,
        "explanation": [],
    }
    defaults.update(kwargs)
    return ConfidenceResult(**defaults)  # type: ignore[arg-type]


class TestNoBuyOrSellInOutput:
    def test_no_forbidden_words_when_passing_gate(self) -> None:
        result = _make_result(passed_gate=True)
        lines = _builder.build(result, _make_context(), _make_score_result())
        full_text = " ".join(lines).upper()
        for word in _FORBIDDEN:
            assert word not in full_text, f"Forbidden word '{word}' in explanation"

    def test_no_forbidden_words_when_failing_gate(self) -> None:
        result = _make_result(
            final_confidence=50.0,
            calibrated_confidence=50.0,
            raw_confidence=50.0,
            passed_gate=False,
        )
        lines = _builder.build(result, _make_context(), _make_score_result())
        full_text = " ".join(lines).upper()
        for word in _FORBIDDEN:
            assert word not in full_text, f"Forbidden word '{word}' in explanation"


class TestExplanationStructure:
    def test_returns_non_empty_list(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert isinstance(lines, list)
        assert len(lines) >= 1

    def test_first_line_contains_gate_label_pass(self) -> None:
        lines = _builder.build(
            _make_result(passed_gate=True), _make_context(), _make_score_result()
        )
        assert "PASS" in lines[0]

    def test_first_line_contains_gate_label_fail(self) -> None:
        result = _make_result(
            final_confidence=50.0,
            calibrated_confidence=50.0,
            raw_confidence=50.0,
            passed_gate=False,
        )
        lines = _builder.build(result, _make_context(), _make_score_result())
        assert "FAIL" in lines[0]

    def test_first_line_contains_direction(self) -> None:
        lines = _builder.build(
            _make_result(), _make_context(), _make_score_result(direction="LONG")
        )
        assert "LONG" in lines[0]

    def test_first_line_contains_bucket(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert "STANDARD" in lines[0]

    def test_gate_fail_line_present_when_not_passing(self) -> None:
        result = _make_result(
            final_confidence=50.0,
            calibrated_confidence=50.0,
            raw_confidence=50.0,
            passed_gate=False,
        )
        lines = _builder.build(result, _make_context(), _make_score_result())
        assert any("NOT eligible" in line for line in lines)

    def test_gate_fail_line_absent_when_passing(self) -> None:
        result = _make_result(passed_gate=True)
        lines = _builder.build(result, _make_context(), _make_score_result())
        assert not any("NOT eligible" in line for line in lines)

    def test_agreement_line_present(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert any("Agreement" in line for line in lines)

    def test_recent_performance_line_present(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert any("Recent" in line for line in lines)

    def test_data_quality_line_present(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert any("Data quality" in line for line in lines)

    def test_regime_line_present(self) -> None:
        lines = _builder.build(_make_result(), _make_context(), _make_score_result())
        assert any("Regime" in line for line in lines)


class TestRegimeAlignment:
    def test_bullish_long_shows_aligned(self) -> None:
        lines = _builder.build(
            _make_result(),
            _make_context(regime=MarketRegime.TRENDING_BULLISH),
            _make_score_result(direction="LONG"),
        )
        regime_line = next(ln for ln in lines if "Regime" in ln)
        assert "ALIGNED" in regime_line

    def test_bullish_short_shows_misaligned(self) -> None:
        lines = _builder.build(
            _make_result(),
            _make_context(regime=MarketRegime.TRENDING_BULLISH),
            _make_score_result(direction="SHORT"),
        )
        regime_line = next(ln for ln in lines if "Regime" in ln)
        assert "MISALIGNED" in regime_line

    def test_sideways_shows_neutral(self) -> None:
        lines = _builder.build(
            _make_result(),
            _make_context(regime=MarketRegime.SIDEWAYS),
            _make_score_result(direction="LONG"),
        )
        regime_line = next(ln for ln in lines if "Regime" in ln)
        assert "NEUTRAL" in regime_line


class TestDeterminism:
    def test_same_inputs_produce_same_output(self) -> None:
        result = _make_result()
        ctx = _make_context()
        sr = _make_score_result()
        assert _builder.build(result, ctx, sr) == _builder.build(result, ctx, sr)
