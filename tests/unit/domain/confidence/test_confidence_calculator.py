"""Unit tests for ConfidenceCalculator — pure domain service.

All tests are synchronous (no async, no I/O, no mocks needed).
Validates AC-11 (determinism), formula correctness, and AC-13 (sub-input auditability).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain.confidence.confidence_calculator import ConfidenceCalculator
from core.domain.enums.market_regime import MarketRegime
from core.domain.value_objects.component_output import ComponentOutput
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_breakdown import ScoreBreakdown
from core.domain.value_objects.score_context import ScoreContext
from core.infrastructure.config.confidence_config import load_confidence_config

_cfg = load_confidence_config()
_calc = ConfidenceCalculator(_cfg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
    india_vix: float | None = 16.0,
) -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m", india_vix=india_vix)
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features,
    )


def _make_score_result(
    direction: str = "LONG",
    adjusted_score: float = 78.0,
    score_quality: str = "MEDIUM",
    data_completeness_pct: float = 100.0,
) -> MagicMock:
    breakdown = ScoreBreakdown(
        oi_buildup=30.0,
        trend=25.0,
        option_chain=15.0,
        volume=10.0,
        vwap=8.0,
        sentiment=5.0,
        iv_analysis=5.0,
        regime_alignment="ALIGNED",
        regime_mismatch=False,
        total_before_penalties=78.0,
    )
    mock = MagicMock()
    mock.direction = direction
    mock.adjusted_score = adjusted_score
    mock.score_breakdown = breakdown
    mock.score_quality = score_quality
    mock.data_completeness_pct = data_completeness_pct
    return mock


def _make_component(
    name: str,
    max_weight: int,
    direction: str = "LONG",
    freshness: int = 0,
    is_available: bool = True,
) -> ComponentOutput:
    long_s = float(max_weight) if direction == "LONG" and is_available else 0.0
    short_s = float(max_weight) if direction == "SHORT" and is_available else 0.0
    return ComponentOutput(
        component_name=name,
        max_weight=max_weight,
        long_score=long_s,
        short_score=short_s,
        direction=direction if is_available else "NEUTRAL",
        conviction=1.0 if is_available else 0.0,
        is_available=is_available,
        data_freshness_seconds=freshness,
        key_finding=f"{name} finding",
    )


def _all_long(freshness: int = 0) -> list[ComponentOutput]:
    return [
        _make_component("OI_BUILDUP", 25, freshness=freshness),
        _make_component("TREND", 20, freshness=freshness),
        _make_component("OPTION_CHAIN", 20, freshness=freshness),
        _make_component("VOLUME", 15, freshness=freshness),
        _make_component("VWAP", 10, freshness=freshness),
        _make_component("SENTIMENT", 5, freshness=freshness),
        _make_component("IV_ANALYSIS", 5, freshness=freshness),
    ]


def _call(**kwargs: object):
    """Call _calc.calculate with sensible defaults, overriding with kwargs."""
    defaults: dict[str, object] = {
        "context": _make_context(),
        "score_result": _make_score_result(),
        "component_outputs": _all_long(),
        "win_rate": None,
        "historical_accuracy": None,
        "consecutive_losses": 0,
        "recent_outcomes_short": [],
        "recent_outcomes_long": [],
    }
    defaults.update(kwargs)
    return _calc.calculate(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-11 — Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_inputs_produce_identical_result(self) -> None:
        r1 = _call()
        r2 = _call()
        assert r1.final_confidence == r2.final_confidence
        assert r1.fingerprint == r2.fingerprint
        assert r1.confidence_components == r2.confidence_components

    def test_identical_inputs_produce_identical_fingerprint(self) -> None:
        ctx = _make_context()
        sr = _make_score_result()
        r1 = _calc.calculate(ctx, sr, _all_long(), None, None, 0, [], [])
        r2 = _calc.calculate(ctx, sr, _all_long(), None, None, 0, [], [])
        assert r1.fingerprint == r2.fingerprint

    def test_different_direction_different_fingerprint(self) -> None:
        r_long = _call(score_result=_make_score_result(direction="LONG"))
        r_short = _call(score_result=_make_score_result(direction="SHORT"))
        assert r_long.fingerprint != r_short.fingerprint

    def test_different_regime_different_fingerprint(self) -> None:
        r1 = _call(context=_make_context(regime=MarketRegime.TRENDING_BULLISH))
        r2 = _call(context=_make_context(regime=MarketRegime.TRENDING_BEARISH))
        assert r1.fingerprint != r2.fingerprint


# ---------------------------------------------------------------------------
# AC-12 — Clamping
# ---------------------------------------------------------------------------

class TestClamping:
    def test_raw_confidence_clamped_to_0_100(self) -> None:
        r = _call()
        assert 0.0 <= r.raw_confidence <= 100.0

    def test_extreme_positive_adjustments_clamped(self) -> None:
        r = _call(
            win_rate=1.0,
            historical_accuracy=(1.0, 50),
            score_result=_make_score_result(adjusted_score=100.0),
        )
        assert r.raw_confidence <= 100.0

    def test_extreme_negative_adjustments_clamped(self) -> None:
        r = _call(
            context=_make_context(regime=MarketRegime.TRENDING_BEARISH),
            score_result=_make_score_result(direction="LONG", adjusted_score=70.0),
            win_rate=0.0,
            historical_accuracy=(0.0, 50),
            consecutive_losses=20,
        )
        assert r.raw_confidence >= 0.0


# ---------------------------------------------------------------------------
# Win rate adjustment
# ---------------------------------------------------------------------------

class TestWinRateAdj:
    def test_none_win_rate_gives_zero(self) -> None:
        r = _call(win_rate=None)
        assert r.win_rate_adj == 0.0

    def test_high_win_rate_gives_adj_high(self) -> None:
        r = _call(win_rate=0.70)  # 70% > threshold_high (65%)
        assert r.win_rate_adj == pytest.approx(_cfg.win_rate.adj_high)

    def test_mid_win_rate_gives_adj_mid(self) -> None:
        r = _call(win_rate=0.60)  # 60% — between 55 and 65
        assert r.win_rate_adj == pytest.approx(_cfg.win_rate.adj_mid)

    def test_low_win_rate_gives_adj_below_low(self) -> None:
        r = _call(win_rate=0.40)  # 40% < 45%
        assert r.win_rate_adj == pytest.approx(_cfg.win_rate.adj_below_low)


# ---------------------------------------------------------------------------
# Regime alignment adjustment
# ---------------------------------------------------------------------------

class TestRegimeAlignmentAdj:
    def test_long_bullish_aligned(self) -> None:
        r = _call(
            context=_make_context(regime=MarketRegime.TRENDING_BULLISH),
            score_result=_make_score_result(direction="LONG"),
        )
        assert r.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_aligned)

    def test_long_bearish_misaligned(self) -> None:
        r = _call(
            context=_make_context(regime=MarketRegime.TRENDING_BEARISH),
            score_result=_make_score_result(direction="LONG"),
        )
        assert r.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_misaligned)

    def test_sideways_neutral(self) -> None:
        r = _call(
            context=_make_context(regime=MarketRegime.SIDEWAYS),
            score_result=_make_score_result(direction="LONG"),
        )
        assert r.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_neutral)

    def test_short_bearish_aligned(self) -> None:
        r = _call(
            context=_make_context(regime=MarketRegime.TRENDING_BEARISH),
            score_result=_make_score_result(direction="SHORT"),
        )
        assert r.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_aligned)


# ---------------------------------------------------------------------------
# Data quality composite (AD-3)
# ---------------------------------------------------------------------------

class TestDataQualityComposite:
    def test_high_quality_gives_adj_high(self) -> None:
        r = _call(
            score_result=_make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            component_outputs=_all_long(freshness=10),
        )
        assert r.data_quality_adj == pytest.approx(_cfg.data_quality.adj_high)

    def test_insufficient_gives_lower_adj(self) -> None:
        r = _call(
            score_result=_make_score_result(
                score_quality="INSUFFICIENT", data_completeness_pct=0.0
            ),
            component_outputs=_all_long(freshness=400),  # all severely stale
        )
        assert r.data_quality_adj <= _cfg.data_quality.adj_mid

    def test_oi_grace_exempt(self) -> None:
        outputs_grace = [
            _make_component("OI_BUILDUP", 25, freshness=200),  # within 300s grace
            *_all_long(freshness=10)[1:],
        ]
        outputs_no_grace = [
            _make_component("OI_BUILDUP", 25, freshness=400),  # beyond grace
            *_all_long(freshness=10)[1:],
        ]
        r_grace = _call(
            score_result=_make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            component_outputs=outputs_grace,
        )
        r_no_grace = _call(
            score_result=_make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            component_outputs=outputs_no_grace,
        )
        assert r_grace.data_quality_adj >= r_no_grace.data_quality_adj

    def test_composite_sub_inputs_in_components(self) -> None:
        r = _call(
            score_result=_make_score_result(score_quality="MEDIUM", data_completeness_pct=80.0),
        )
        cc = r.confidence_components
        assert 0.0 <= cc["dq_score_quality_score"] <= 100.0
        assert 0.0 <= cc["dq_completeness_score"] <= 100.0
        assert 0.0 <= cc["dq_freshness_score"] <= 100.0
        assert 0.0 <= cc["dq_composite"] <= 100.0

    def test_staleness_reduces_freshness_sub_score(self) -> None:
        r_fresh = _call(
            score_result=_make_score_result(score_quality="MEDIUM", data_completeness_pct=100.0),
            component_outputs=_all_long(freshness=0),
        )
        r_stale = _call(
            score_result=_make_score_result(score_quality="MEDIUM", data_completeness_pct=100.0),
            component_outputs=_all_long(freshness=200),  # mild staleness on all
        )
        assert (
            r_fresh.confidence_components["dq_freshness_score"]
            >= r_stale.confidence_components["dq_freshness_score"]
        )


# ---------------------------------------------------------------------------
# Signal agreement (AD-5)
# ---------------------------------------------------------------------------

class TestSignalAgreement:
    def test_full_agreement_gives_adj_high(self) -> None:
        r = _call(
            score_result=_make_score_result(direction="LONG"),
            component_outputs=_all_long(),
        )
        assert r.signal_agreement_adj == pytest.approx(_cfg.signal_agreement.adj_high)

    def test_zero_agreement_gives_adj_below_low(self) -> None:
        outputs = [
            _make_component(name, w, direction="SHORT")
            for name, w in [
                ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
                ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5),
            ]
        ]
        r = _call(
            score_result=_make_score_result(direction="LONG"),
            component_outputs=outputs,
        )
        assert r.signal_agreement_adj == pytest.approx(_cfg.signal_agreement.adj_below_low)

    def test_no_available_components_gives_zero(self) -> None:
        outputs = [
            _make_component(name, w, is_available=False)
            for name, w in [
                ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
                ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5),
            ]
        ]
        r = _call(component_outputs=outputs)
        assert r.signal_agreement_adj == 0.0

    def test_pct_recorded_accurately(self) -> None:
        # 5 LONG, 2 SHORT — direction=LONG → 5/7 = 71.4% → adj_mid (71.0 ≤ pct < 85.0)
        outputs = [
            _make_component("OI_BUILDUP", 25, direction="LONG"),
            _make_component("TREND", 20, direction="LONG"),
            _make_component("OPTION_CHAIN", 20, direction="LONG"),
            _make_component("VOLUME", 15, direction="LONG"),
            _make_component("VWAP", 10, direction="LONG"),
            _make_component("SENTIMENT", 5, direction="SHORT"),
            _make_component("IV_ANALYSIS", 5, direction="SHORT"),
        ]
        r = _call(
            score_result=_make_score_result(direction="LONG"),
            component_outputs=outputs,
        )
        expected_pct = (5 / 7) * 100.0
        assert r.confidence_components["sa_pct"] == pytest.approx(expected_pct, abs=0.01)


# ---------------------------------------------------------------------------
# Recent performance (AD-4)
# ---------------------------------------------------------------------------

class TestRecentPerformance:
    def test_empty_outcomes_gives_zero(self) -> None:
        r = _call(recent_outcomes_short=[], recent_outcomes_long=[])
        assert r.recent_performance_adj == 0.0

    def test_all_wins_short_window_gives_adj_high(self) -> None:
        r = _call(
            recent_outcomes_short=["WIN"] * 20,
            recent_outcomes_long=["WIN"] * 50,
        )
        assert r.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_high)

    def test_all_losses_gives_adj_below_low(self) -> None:
        r = _call(
            recent_outcomes_short=["LOSS"] * 20,
            recent_outcomes_long=["LOSS"] * 50,
        )
        assert r.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_below_low)

    def test_only_short_window_uses_short_fully(self) -> None:
        r = _call(
            recent_outcomes_short=["WIN"] * 20,
            recent_outcomes_long=[],
        )
        # 100% wins in short → combined_pct = 100 → adj_high
        assert r.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_high)

    def test_weighted_combination(self) -> None:
        # short window: 80% wins (16/20) → short_pct=80
        # long window: 50% wins (25/50) → long_pct=50
        # combined = 0.70*80 + 0.30*50 = 56 + 15 = 71 > threshold_high(65) → adj_high
        r = _call(
            recent_outcomes_short=["WIN"] * 16 + ["LOSS"] * 4,
            recent_outcomes_long=["WIN"] * 25 + ["LOSS"] * 25,
        )
        assert r.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_high)

    def test_win_pcts_in_components(self) -> None:
        r = _call(
            recent_outcomes_short=["WIN"] * 10 + ["LOSS"] * 10,
            recent_outcomes_long=["WIN"] * 25 + ["LOSS"] * 25,
        )
        assert r.confidence_components["rp_short_win_pct"] == pytest.approx(50.0)
        assert r.confidence_components["rp_long_win_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Historical accuracy adjustment
# ---------------------------------------------------------------------------

class TestHistoricalAccuracyAdj:
    def test_none_gives_neutral(self) -> None:
        r = _call(historical_accuracy=None)
        assert r.historical_accuracy_adj == pytest.approx(_cfg.historical_accuracy.adj_neutral)

    def test_high_accuracy_full_samples(self) -> None:
        r = _call(historical_accuracy=(0.75, 35))
        assert r.historical_accuracy_adj == pytest.approx(_cfg.historical_accuracy.adj_high_full)

    def test_high_accuracy_partial_samples(self) -> None:
        r = _call(historical_accuracy=(0.75, 15))
        assert r.historical_accuracy_adj == pytest.approx(
            _cfg.historical_accuracy.adj_high_partial
        )

    def test_low_accuracy_full_samples_gives_negative(self) -> None:
        r = _call(historical_accuracy=(0.40, 35))
        assert r.historical_accuracy_adj == pytest.approx(_cfg.historical_accuracy.adj_low_full)


# ---------------------------------------------------------------------------
# Loss streak adjustment
# ---------------------------------------------------------------------------

class TestLossStreakAdj:
    def test_no_streak_zero(self) -> None:
        r = _call(consecutive_losses=0)
        assert r.loss_streak_adj == 0.0

    def test_streak_of_3(self) -> None:
        r = _call(consecutive_losses=3)
        expected = max(_cfg.loss_streak.floor, _cfg.loss_streak.adj_per_loss * 3)
        assert r.loss_streak_adj == pytest.approx(expected)

    def test_large_streak_floored(self) -> None:
        r = _call(consecutive_losses=100)
        assert r.loss_streak_adj == pytest.approx(_cfg.loss_streak.floor)


# ---------------------------------------------------------------------------
# fingerprint_for static helper
# ---------------------------------------------------------------------------

class TestFingerprintFor:
    def test_matches_internal_fingerprint(self) -> None:
        ctx = _make_context()
        sr = _make_score_result()
        expected = _calc.calculate(ctx, sr, _all_long(), None, None, 0, [], []).fingerprint
        assert ConfidenceCalculator.fingerprint_for(ctx, sr) == expected

    def test_deterministic(self) -> None:
        ctx = _make_context()
        sr = _make_score_result()
        fp1 = ConfidenceCalculator.fingerprint_for(ctx, sr)
        fp2 = ConfidenceCalculator.fingerprint_for(ctx, sr)
        assert fp1 == fp2
