"""Unit tests for ScoreExplanationBuilder."""

from __future__ import annotations

from core.domain.enums.market_regime import MarketRegime
from core.domain.scoring.score_explanation_builder import ScoreExplanationBuilder
from core.domain.value_objects.component_output import ComponentOutput
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_breakdown import ScoreBreakdown
from core.domain.value_objects.score_context import ScoreContext
from core.domain.value_objects.score_penalty import ScorePenalty
from core.domain.value_objects.score_result import ScoreResult

_FORBIDDEN_WORDS = {"BUY", "SELL", "ORDER", "TRADE", "ENTRY", "STOP_LOSS", "TARGET"}


def _breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        oi_buildup=20.0,
        trend=15.0,
        option_chain=10.0,
        volume=8.0,
        vwap=5.0,
        sentiment=2.0,
        iv_analysis=2.0,
        regime_alignment="ALIGNED",
        regime_mismatch=False,
        total_before_penalties=62.0,
    )


def _result(
    direction: str = "LONG",
    is_eligible: bool = True,
    penalties: list[ScorePenalty] | None = None,
    score_quality: str = "HIGH",
) -> ScoreResult:
    return ScoreResult(
        direction=direction,
        direction_conviction=0.75,
        raw_score=75.0,
        adjusted_score=67.0 if penalties else 75.0,
        score_breakdown=_breakdown(),
        penalties=penalties or [],
        data_completeness_pct=100.0,
        is_eligible=is_eligible,
        score_quality=score_quality,
        weights_sha256="abc123",
    )


def _ctx() -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m")
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=MarketRegime.TRENDING_BULLISH,
        features=features,
    )


def _outputs(direction: str = "LONG") -> list[ComponentOutput]:
    names = [
        ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
        ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5),
    ]
    out = []
    for name, w in names:
        ds = float(w)
        out.append(ComponentOutput(
            component_name=name, max_weight=w,
            long_score=ds if direction != "SHORT" else 0.0,
            short_score=ds if direction == "SHORT" else 0.0,
            direction=direction, conviction=1.0,
            is_available=True, data_freshness_seconds=0,
            key_finding=f"{name} finding text",
        ))
    # One unavailable component
    out.append(ComponentOutput(
        component_name="IV_ANALYSIS", max_weight=5,
        long_score=0.0, short_score=0.0,
        direction="NEUTRAL", conviction=0.0,
        is_available=False, data_freshness_seconds=0,
        key_finding="INSUFFICIENT_DATA: iv_data not available",
    ))
    return out


class TestExplanationContent:
    def test_summary_line_present(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        assert len(lines) > 0
        assert any("LONG" in line or "adjusted" in line.lower() for line in lines[:2])

    def test_data_completeness_mentioned(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        text = "\n".join(lines)
        assert "%" in text or "completeness" in text.lower()

    def test_regime_line_present(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        text = "\n".join(lines)
        assert "TRENDING_BULLISH" in text or "regime" in text.lower()

    def test_components_listed_in_output(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        text = "\n".join(lines)
        assert "OI_BUILDUP" in text

    def test_unavailable_component_listed(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        text = "\n".join(lines)
        assert "IV_ANALYSIS" in text

    def test_penalties_section_when_present(self) -> None:
        penalty = ScorePenalty("REGIME_MISMATCH", -20.0, "signal opposed regime")
        lines = ScoreExplanationBuilder().build(
            _result(penalties=[penalty]), _outputs(), _ctx()
        )
        text = "\n".join(lines)
        assert "REGIME_MISMATCH" in text

    def test_no_penalty_section_when_none(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(penalties=[]), _outputs(), _ctx())
        text = "\n".join(lines)
        assert "Penalties" not in text or "-0.0" not in text

    def test_no_forbidden_words(self) -> None:
        lines = ScoreExplanationBuilder().build(_result(), _outputs(), _ctx())
        text = " ".join(lines).upper()
        for word in _FORBIDDEN_WORDS:
            assert word not in text, f"Forbidden word '{word}' found in explanation"

    def test_ineligible_result_returns_early(self) -> None:
        lines = ScoreExplanationBuilder().build(
            _result(direction="NEUTRAL", is_eligible=False), _outputs("NEUTRAL"), _ctx()
        )
        text = "\n".join(lines)
        assert "not eligible" in text.lower() or "INELIGIBLE" in text

    def test_deterministic_output(self) -> None:
        builder = ScoreExplanationBuilder()
        r = _result()
        outputs = _outputs()
        ctx = _ctx()
        lines1 = builder.build(r, outputs, ctx)
        lines2 = builder.build(r, outputs, ctx)
        assert lines1 == lines2
