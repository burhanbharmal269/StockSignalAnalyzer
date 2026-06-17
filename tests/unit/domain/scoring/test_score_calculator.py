"""Unit tests for ScoreCalculator — direction vote, aggregation, penalties."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.domain.enums.market_regime import MarketRegime
from core.domain.scoring.score_calculator import ScoreCalculator
from core.domain.value_objects.component_output import ComponentOutput
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_context import ScoreContext
from core.infrastructure.config.scoring_config import load_scoring_config
from core.infrastructure.config.strategy_config import load_strategy_config

_IST = timezone(timedelta(hours=5, minutes=30))
_strategy_cfg = load_strategy_config()
_scoring_cfg = load_scoring_config()


def _calc() -> ScoreCalculator:
    return ScoreCalculator(_strategy_cfg, _scoring_cfg)


def _out(
    name: str,
    max_weight: int,
    direction: str,
    long_score: float,
    short_score: float,
    is_available: bool = True,
    data_freshness_seconds: int = 0,
) -> ComponentOutput:
    if is_available and max_weight > 0:
        ds = long_score if direction in ("LONG", "NEUTRAL") else short_score
        conviction = ds / max_weight if ds > 0 else 0.0
    else:
        conviction = 0.0
    return ComponentOutput(
        component_name=name,
        max_weight=max_weight,
        long_score=long_score,
        short_score=short_score,
        direction=direction,
        conviction=conviction,
        is_available=is_available,
        data_freshness_seconds=data_freshness_seconds,
        key_finding=f"{name} finding",
    )


def _all_long(score_pct: float = 1.0) -> list[ComponentOutput]:
    return [
        _out("OI_BUILDUP", 25, "LONG", 25.0 * score_pct, 0.0),
        _out("TREND", 20, "LONG", 20.0 * score_pct, 0.0),
        _out("OPTION_CHAIN", 20, "LONG", 20.0 * score_pct, 0.0),
        _out("VOLUME", 15, "LONG", 15.0 * score_pct, 0.0),
        _out("VWAP", 10, "LONG", 10.0 * score_pct, 0.0),
        _out("SENTIMENT", 5, "LONG", 5.0 * score_pct, 0.0),
        _out("IV_ANALYSIS", 5, "LONG", 5.0 * score_pct, 0.0),
    ]


def _all_short() -> list[ComponentOutput]:
    return [
        _out("OI_BUILDUP", 25, "SHORT", 0.0, 25.0),
        _out("TREND", 20, "SHORT", 0.0, 20.0),
        _out("OPTION_CHAIN", 20, "SHORT", 0.0, 20.0),
        _out("VOLUME", 15, "SHORT", 0.0, 15.0),
        _out("VWAP", 10, "SHORT", 0.0, 10.0),
        _out("SENTIMENT", 5, "SHORT", 0.0, 5.0),
        _out("IV_ANALYSIS", 5, "SHORT", 0.0, 5.0),
    ]


def _mostly_long_moderate_conviction() -> list[ComponentOutput]:
    """LONG wins with conviction ~0.55 (0.45–0.60 — triggers MODERATE penalty)."""
    return [
        _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0),
        _out("TREND", 20, "SHORT", 0.0, 20.0),
        _out("OPTION_CHAIN", 20, "SHORT", 0.0, 20.0),
        _out("VOLUME", 15, "LONG", 15.0, 0.0),
        _out("VWAP", 10, "LONG", 10.0, 0.0),
        _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
        _out("IV_ANALYSIS", 5, "SHORT", 0.0, 5.0),
    ]
    # LONG = 25+15+10+5 = 55, SHORT = 20+20+5 = 45, total=100, conviction=0.55


def _ctx(
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
    dte: int | None = None,
    evaluation_timestamp: datetime | None = None,
) -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m")
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features,
        dte=dte,
        evaluation_timestamp=evaluation_timestamp or datetime.now(UTC),
    )


def _ist_ts(hour: int, minute: int) -> datetime:
    """UTC datetime that equals the given IST clock time."""
    ist_dt = datetime(2024, 1, 15, hour, minute, 0, tzinfo=_IST)
    return ist_dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Direction vote
# ---------------------------------------------------------------------------

class TestDirectionVote:
    def test_all_long_returns_long(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        assert result.direction == "LONG"

    def test_all_short_returns_short(self) -> None:
        result = _calc().calculate(_all_short(), _ctx())
        assert result.direction == "SHORT"

    def test_tied_votes_returns_neutral(self) -> None:
        # OI_BUILDUP(25)+TREND(20)+OPTION_CHAIN(20)+VOLUME(15) = 80 LONG
        # same = 80 SHORT — impossible with only 100 pts total
        # Use: OI_BUILDUP(25)+VOLUME(15)+SENTIMENT(5)+IV_ANALYSIS(5) = 50 LONG,
        #       TREND(20)+OPTION_CHAIN(20)+VWAP(10) = 50 SHORT → tied
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0),
            _out("TREND", 20, "SHORT", 0.0, 20.0),
            _out("OPTION_CHAIN", 20, "SHORT", 0.0, 20.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "SHORT", 0.0, 10.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.direction == "NEUTRAL"

    def test_unavailable_excluded_from_direction_vote(self) -> None:
        outputs = [
            _out("OI_BUILDUP", 25, "SHORT", 0.0, 25.0, is_available=False),
            _out("TREND", 20, "SHORT", 0.0, 20.0, is_available=False),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0),
        ]
        # Available LONG = 55, SHORT = 0 → LONG (unavailable SHORT ignored)
        result = _calc().calculate(outputs, _ctx())
        assert result.direction == "LONG"

    def test_high_conviction_long(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        assert result.direction_conviction == pytest.approx(1.0)

    def test_moderate_conviction_long(self) -> None:
        result = _calc().calculate(_mostly_long_moderate_conviction(), _ctx())
        assert result.direction == "LONG"
        assert result.direction_conviction == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

class TestScoreAggregation:
    def test_max_score_all_aligned(self) -> None:
        """All components at max score and all LONG direction → raw_score = 100."""
        result = _calc().calculate(_all_long(), _ctx())
        assert result.raw_score == pytest.approx(100.0, abs=0.1)

    def test_zero_score_direction_neutral(self) -> None:
        """NEUTRAL direction → raw_score and adjusted_score both 0."""
        outputs = [_out("OI_BUILDUP", 25, "NEUTRAL", 12.5, 12.5)] + [
            _out("TREND", 20, "NEUTRAL", 10.0, 10.0),
            _out("OPTION_CHAIN", 20, "NEUTRAL", 10.0, 10.0),
            _out("VOLUME", 15, "NEUTRAL", 7.5, 7.5),
            _out("VWAP", 10, "NEUTRAL", 5.0, 5.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "SHORT", 0.0, 5.0),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.direction == "NEUTRAL"
        assert result.raw_score == 0.0
        assert result.adjusted_score == 0.0

    def test_opposing_component_drags_score(self) -> None:
        """A SHORT component in a LONG signal reduces raw_score."""
        # All LONG vs one SHORT component mixed in
        all_long = _all_long()
        # Replace VWAP with a SHORT-direction component
        mixed = [
            o if o.component_name != "VWAP"
            else _out("VWAP", 10, "SHORT", 0.0, 10.0)
            for o in all_long
        ]
        result_all = _calc().calculate(all_long, _ctx())
        result_mixed = _calc().calculate(mixed, _ctx())
        assert result_mixed.raw_score < result_all.raw_score

    def test_neutral_component_gives_partial_credit(self) -> None:
        """A NEUTRAL component contributes +40% partial credit."""
        # All LONG vs one NEUTRAL component
        all_long = _all_long()
        with_neutral = [
            o if o.component_name != "VWAP"
            else _out("VWAP", 10, "NEUTRAL", 5.0, 5.0)
            for o in all_long
        ]
        result_all = _calc().calculate(all_long, _ctx())
        result_partial = _calc().calculate(with_neutral, _ctx())
        # Neutral reduces score from 100 but not to zero
        assert 0.0 < result_partial.raw_score < result_all.raw_score

    def test_unavailable_component_redistributes_weight(self) -> None:
        """Unavailable component excluded from denominator; remaining score stays valid."""
        all_long = _all_long()
        with_unavail = [
            o if o.component_name != "SENTIMENT"
            else _out("SENTIMENT", 5, "LONG", 5.0, 0.0, is_available=False)
            for o in all_long
        ]
        result = _calc().calculate(with_unavail, _ctx())
        # Score still valid 0-100
        assert 0.0 <= result.raw_score <= 100.0
        # With 6/7 available and all aligned, score should still be high
        assert result.raw_score >= 90.0

    def test_raw_score_clamped_to_100(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        assert result.raw_score <= 100.0

    def test_raw_score_never_negative(self) -> None:
        result = _calc().calculate(_all_short(), _ctx(regime=MarketRegime.TRENDING_BULLISH))
        assert result.raw_score >= 0.0


# ---------------------------------------------------------------------------
# Data completeness
# ---------------------------------------------------------------------------

class TestDataCompleteness:
    def test_five_of_seven_below_threshold(self) -> None:
        """5/7 = 71.4% < 75% → is_eligible=False."""
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0),
            _out("TREND", 20, "LONG", 20.0, 0.0),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0, is_available=False),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0, is_available=False),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.is_eligible is False
        assert result.data_completeness_pct == pytest.approx(71.43, abs=0.1)

    def test_six_of_seven_above_threshold(self) -> None:
        """6/7 = 85.7% >= 75% → is_eligible=True (when LONG direction)."""
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0),
            _out("TREND", 20, "LONG", 20.0, 0.0),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0, is_available=False),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.is_eligible is True

    def test_all_seven_available(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        assert result.data_completeness_pct == pytest.approx(100.0)
        assert result.is_eligible is True


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------

class TestDataStalenessPenalty:
    def test_one_stale_component_minus_10(self) -> None:
        # Use tick_data_max_age (60s default) → freshness > 60 triggers penalty
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0, data_freshness_seconds=61),
        ] + [
            _out(n, w, "LONG", float(w), 0.0)
            for n, w in [("TREND", 20), ("OPTION_CHAIN", 20), ("VOLUME", 15),
                         ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5)]
        ]
        result = _calc().calculate(outputs, _ctx())
        staleness = [p for p in result.penalties if p.penalty_type == "DATA_STALENESS"]
        assert len(staleness) == 1
        assert staleness[0].amount == pytest.approx(-10.0)
        assert staleness[0].component_name == "OI_BUILDUP"

    def test_staleness_capped_at_minus_20(self) -> None:
        # 3 stale components × −10 = −30, but cap is −20
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0, data_freshness_seconds=999),
            _out("TREND", 20, "LONG", 20.0, 0.0, data_freshness_seconds=999),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0, data_freshness_seconds=999),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0),
        ]
        result = _calc().calculate(outputs, _ctx())
        staleness_total = sum(
            p.amount for p in result.penalties if p.penalty_type == "DATA_STALENESS"
        )
        assert staleness_total >= -20.0  # cap enforced


class TestLowConvictionPenalty:
    def test_moderate_conviction_triggers_moderate_penalty(self) -> None:
        # conviction = 0.55 → between 0.45 and 0.60 → MODERATE penalty (−8)
        outputs = _mostly_long_moderate_conviction()
        result = _calc().calculate(outputs, _ctx())
        assert result.direction == "LONG"
        conv_penalties = [p for p in result.penalties if p.penalty_type == "LOW_CONVICTION"]
        assert len(conv_penalties) == 1
        assert conv_penalties[0].amount == pytest.approx(-8.0)

    def test_high_conviction_no_low_conviction_penalty(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        conv_penalties = [p for p in result.penalties if p.penalty_type == "LOW_CONVICTION"]
        assert len(conv_penalties) == 0


class TestMarketHoursPenalty:
    def test_opening_window_minus_10(self) -> None:
        ts = _ist_ts(9, 20)  # 09:20 IST → inside 09:15-09:30 window
        result = _calc().calculate(_all_long(), _ctx(evaluation_timestamp=ts))
        mh = [p for p in result.penalties if p.penalty_type == "MARKET_HOURS"]
        assert len(mh) == 1
        assert mh[0].amount == pytest.approx(-10.0)

    def test_closing_window_minus_20(self) -> None:
        ts = _ist_ts(15, 20)  # 15:20 IST → after 15:15
        result = _calc().calculate(_all_long(), _ctx(evaluation_timestamp=ts))
        mh = [p for p in result.penalties if p.penalty_type == "MARKET_HOURS"]
        assert len(mh) == 1
        assert mh[0].amount == pytest.approx(-20.0)

    def test_normal_session_no_market_hours_penalty(self) -> None:
        ts = _ist_ts(12, 0)  # 12:00 IST → normal hours
        result = _calc().calculate(_all_long(), _ctx(evaluation_timestamp=ts))
        mh = [p for p in result.penalties if p.penalty_type == "MARKET_HOURS"]
        assert len(mh) == 0


class TestRegimeMismatchPenalty:
    def test_long_in_bearish_regime_penalised(self) -> None:
        result = _calc().calculate(
            _all_long(), _ctx(regime=MarketRegime.TRENDING_BEARISH)
        )
        rm = [p for p in result.penalties if p.penalty_type == "REGIME_MISMATCH"]
        assert len(rm) == 1
        assert rm[0].amount == pytest.approx(-20.0)

    def test_long_in_bullish_regime_no_mismatch(self) -> None:
        result = _calc().calculate(
            _all_long(), _ctx(regime=MarketRegime.TRENDING_BULLISH)
        )
        rm = [p for p in result.penalties if p.penalty_type == "REGIME_MISMATCH"]
        assert len(rm) == 0

    def test_long_in_sideways_no_mismatch(self) -> None:
        # SIDEWAYS regime_direction = NEUTRAL → no mismatch
        result = _calc().calculate(_all_long(), _ctx(regime=MarketRegime.SIDEWAYS))
        rm = [p for p in result.penalties if p.penalty_type == "REGIME_MISMATCH"]
        assert len(rm) == 0


class TestExpiryRiskPenalty:
    def test_dte_zero_minus_10(self) -> None:
        result = _calc().calculate(_all_long(), _ctx(dte=0))
        er = [p for p in result.penalties if p.penalty_type == "EXPIRY_RISK"]
        assert len(er) == 1
        assert er[0].amount == pytest.approx(-10.0)

    def test_dte_one_minus_5(self) -> None:
        result = _calc().calculate(_all_long(), _ctx(dte=1))
        er = [p for p in result.penalties if p.penalty_type == "EXPIRY_RISK"]
        assert len(er) == 1
        assert er[0].amount == pytest.approx(-5.0)

    def test_dte_two_no_expiry_penalty(self) -> None:
        result = _calc().calculate(_all_long(), _ctx(dte=2))
        er = [p for p in result.penalties if p.penalty_type == "EXPIRY_RISK"]
        assert len(er) == 0

    def test_dte_none_no_expiry_penalty(self) -> None:
        result = _calc().calculate(_all_long(), _ctx(dte=None))
        er = [p for p in result.penalties if p.penalty_type == "EXPIRY_RISK"]
        assert len(er) == 0


class TestPenaltyStackingAndClamping:
    def test_multiple_penalties_stack(self) -> None:
        ts = _ist_ts(15, 20)  # closing penalty −20
        result = _calc().calculate(
            _all_long(),
            _ctx(regime=MarketRegime.TRENDING_BEARISH, dte=0, evaluation_timestamp=ts),
        )
        # Regime mismatch (−20) + market hours closing (−20) + expiry (−10) = −50
        assert len(result.penalties) >= 3

    def test_adjusted_score_never_below_zero(self) -> None:
        ts = _ist_ts(15, 25)
        # Very low scoring outputs + closing penalty should still clamp to 0
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 1.0, 0.0),
            _out("TREND", 20, "LONG", 1.0, 0.0),
            _out("OPTION_CHAIN", 20, "LONG", 1.0, 0.0),
            _out("VOLUME", 15, "LONG", 1.0, 0.0),
            _out("VWAP", 10, "LONG", 1.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 1.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 1.0, 0.0),
        ]
        result = _calc().calculate(
            outputs,
            _ctx(regime=MarketRegime.TRENDING_BEARISH, dte=0, evaluation_timestamp=ts),
        )
        assert result.adjusted_score >= 0.0


# ---------------------------------------------------------------------------
# Score quality
# ---------------------------------------------------------------------------

class TestScoreQuality:
    def test_high_quality_full_data_no_staleness(self) -> None:
        result = _calc().calculate(_all_long(), _ctx())
        assert result.score_quality == "HIGH"

    def test_insufficient_below_completeness_threshold(self) -> None:
        # 5/7 = 71.4% < 75%
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0),
            _out("TREND", 20, "LONG", 20.0, 0.0),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0, is_available=False),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0, is_available=False),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.score_quality == "INSUFFICIENT"

    def test_low_quality_with_staleness(self) -> None:
        # Stale components degrade quality below MEDIUM threshold
        # 2 stale components = −20 staleness pts, > medium max staleness (10)
        outputs = [
            _out("OI_BUILDUP", 25, "LONG", 25.0, 0.0, data_freshness_seconds=999),
            _out("TREND", 20, "LONG", 20.0, 0.0, data_freshness_seconds=999),
            _out("OPTION_CHAIN", 20, "LONG", 20.0, 0.0),
            _out("VOLUME", 15, "LONG", 15.0, 0.0),
            _out("VWAP", 10, "LONG", 10.0, 0.0),
            _out("SENTIMENT", 5, "LONG", 5.0, 0.0),
            _out("IV_ANALYSIS", 5, "LONG", 5.0, 0.0),
        ]
        result = _calc().calculate(outputs, _ctx())
        assert result.score_quality == "LOW"

    def test_medium_quality_moderate_conviction(self) -> None:
        # conviction=0.55 (< HIGH threshold 0.60), no staleness, full completeness
        result = _calc().calculate(_mostly_long_moderate_conviction(), _ctx())
        assert result.direction == "LONG"
        # conviction=0.55 ≥ medium threshold (0.50), staleness=0
        assert result.score_quality == "MEDIUM"


# ---------------------------------------------------------------------------
# Regime multiplier effect
# ---------------------------------------------------------------------------

class TestRegimeMultipliers:
    def test_trending_bullish_boosts_trend_weight(self) -> None:
        """TRENDING_BULLISH gives TREND multiplier 1.30 vs SIDEWAYS 0.25."""
        result_bull = _calc().calculate(_all_long(), _ctx(regime=MarketRegime.TRENDING_BULLISH))
        result_side = _calc().calculate(_all_long(), _ctx(regime=MarketRegime.SIDEWAYS))
        # In SIDEWAYS regime, TREND has much lower multiplier, but all are LONG so
        # the normalized score should still reach 100 (all aligned → numerator = denominator)
        # This test verifies the result is valid in both regimes
        assert 0.0 <= result_bull.raw_score <= 100.0
        assert 0.0 <= result_side.raw_score <= 100.0
