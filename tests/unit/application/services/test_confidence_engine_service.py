"""Unit tests for ConfidenceEngineService.

The service orchestrates async I/O and delegates the formula to ConfidenceCalculator.
Tests use a real ConfidenceCalculator (with loaded config) and mock the repository
and Redis client to isolate I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.confidence_engine_service import ConfidenceEngineService
from core.domain.confidence.confidence_calculator import ConfidenceCalculator
from core.domain.confidence.confidence_explanation_builder import ConfidenceExplanationBuilder
from core.domain.enums.instrument_class import InstrumentClass
from core.domain.enums.market_regime import MarketRegime
from core.domain.events.signal_events import ConfidenceCalculated
from core.domain.value_objects.component_output import ComponentOutput
from core.domain.value_objects.confidence_result import ConfidenceResult
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.domain.value_objects.score_context import ScoreContext
from core.infrastructure.config.confidence_config import load_confidence_config

_cfg = load_confidence_config()
_calc = ConfidenceCalculator(_cfg)
_builder = ConfidenceExplanationBuilder(_cfg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_component(
    name: str,
    max_weight: int,
    direction: str = "LONG",
    freshness: int = 0,
    is_available: bool = True,
) -> ComponentOutput:
    score_pct = 1.0 if is_available else 0.0
    long_s = float(max_weight) * score_pct if direction != "SHORT" else 0.0
    short_s = float(max_weight) * score_pct if direction == "SHORT" else 0.0
    return ComponentOutput(
        component_name=name,
        max_weight=max_weight,
        long_score=long_s if is_available else 0.0,
        short_score=short_s if is_available else 0.0,
        direction=direction if is_available else "NEUTRAL",
        conviction=score_pct if is_available else 0.0,
        is_available=is_available,
        data_freshness_seconds=freshness,
        key_finding=f"{name} finding",
    )


def _all_long_outputs(freshness: int = 0) -> list[ComponentOutput]:
    return [
        _make_component("OI_BUILDUP", 25, freshness=freshness),
        _make_component("TREND", 20, freshness=freshness),
        _make_component("OPTION_CHAIN", 20, freshness=freshness),
        _make_component("VOLUME", 15, freshness=freshness),
        _make_component("VWAP", 10, freshness=freshness),
        _make_component("SENTIMENT", 5, freshness=freshness),
        _make_component("IV_ANALYSIS", 5, freshness=freshness),
    ]


def _make_score_result(
    direction: str = "LONG",
    adjusted_score: float = 78.0,
    score_quality: str = "MEDIUM",
    data_completeness_pct: float = 100.0,
) -> MagicMock:
    from core.domain.value_objects.score_breakdown import ScoreBreakdown

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
    mock.is_eligible = True
    mock.score_quality = score_quality
    mock.data_completeness_pct = data_completeness_pct
    return mock


def _make_context(
    regime: MarketRegime = MarketRegime.TRENDING_BULLISH,
    india_vix: float | None = 16.0,
    instrument_class: InstrumentClass | None = InstrumentClass.INDEX_OPTION,
) -> ScoreContext:
    features = FeatureSnapshot(instrument_token=256265, timeframe="15m", india_vix=india_vix)
    return ScoreContext(
        instrument_token=256265,
        timeframe="15m",
        regime=regime,
        features=features,
        instrument_class=instrument_class,
    )


def _make_repo(
    win_rate: float | None = None,
    historical_accuracy: tuple[float, int] | None = None,
    consecutive_losses: int = 0,
    recent_outcomes: list[str] | None = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.get_win_rate.return_value = win_rate
    repo.get_historical_accuracy.return_value = historical_accuracy
    repo.get_consecutive_losses.return_value = consecutive_losses
    repo.get_recent_outcomes.return_value = recent_outcomes or []
    return repo


def _make_service(
    repo: AsyncMock | None = None,
    redis: AsyncMock | None = None,
    bus: AsyncMock | None = None,
) -> ConfidenceEngineService:
    if repo is None:
        repo = _make_repo()
    if redis is None:
        redis = AsyncMock()
        redis.get.return_value = None
    if bus is None:
        bus = AsyncMock()
    return ConfidenceEngineService(
        performance_repository=repo,
        redis_client=redis,
        config=_cfg,
        event_bus=bus,
        calculator=_calc,
        explanation_builder=_builder,
    )


# ---------------------------------------------------------------------------
# Base behaviour
# ---------------------------------------------------------------------------

class TestConfidenceEngineServiceBase:
    @pytest.mark.asyncio
    async def test_returns_confidence_result(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert isinstance(result, ConfidenceResult)

    @pytest.mark.asyncio
    async def test_base_confidence_uses_score_multiplier(self) -> None:
        svc = _make_service()
        score = 80.0
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(adjusted_score=score), _all_long_outputs()
        )
        expected_base = min(_cfg.base.ceiling, score * _cfg.base.score_multiplier)
        assert result.base_confidence == pytest.approx(expected_base)

    @pytest.mark.asyncio
    async def test_base_confidence_capped_at_ceiling(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(adjusted_score=100.0), _all_long_outputs()
        )
        assert result.base_confidence <= _cfg.base.ceiling

    @pytest.mark.asyncio
    async def test_final_confidence_within_bounds(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert 0.0 <= result.final_confidence <= 100.0

    @pytest.mark.asyncio
    async def test_explanation_non_empty(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert len(result.explanation) > 0

    @pytest.mark.asyncio
    async def test_explanation_no_forbidden_words(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        forbidden = {"BUY", "SELL", "ORDER", "TRADE", "ENTRY", "STOP_LOSS", "TARGET"}
        full_text = " ".join(result.explanation).upper()
        for word in forbidden:
            assert word not in full_text, f"Forbidden word '{word}' found in explanation"

    @pytest.mark.asyncio
    async def test_confidence_components_contains_all_adjustments(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        required_keys = {
            "base_confidence", "win_rate_adj", "regime_alignment_adj", "data_quality_adj",
            "momentum_adj", "breakout_adj", "loss_streak_adj", "historical_accuracy_adj",
            "signal_agreement_adj", "recent_performance_adj",
            "dq_score_quality_score", "dq_completeness_score", "dq_freshness_score",
            "dq_composite", "sa_agreeing", "sa_available", "sa_pct",
            "rp_short_win_pct", "rp_long_win_pct", "rp_combined_pct",
        }
        assert required_keys.issubset(result.confidence_components.keys())

    @pytest.mark.asyncio
    async def test_new_adj_fields_on_result(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert isinstance(result.signal_agreement_adj, float)
        assert isinstance(result.recent_performance_adj, float)


# ---------------------------------------------------------------------------
# Event publication
# ---------------------------------------------------------------------------

class TestEventPublication:
    @pytest.mark.asyncio
    async def test_event_published_always(self) -> None:
        bus = AsyncMock()
        svc = _make_service(bus=bus)
        await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        bus.publish.assert_called_once()
        assert isinstance(bus.publish.call_args[0][0], ConfidenceCalculated)

    @pytest.mark.asyncio
    async def test_event_contains_new_adj_fields(self) -> None:
        bus = AsyncMock()
        svc = _make_service(bus=bus)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        event: ConfidenceCalculated = bus.publish.call_args[0][0]
        assert event.signal_agreement_adj == pytest.approx(result.signal_agreement_adj)
        assert event.recent_performance_adj == pytest.approx(result.recent_performance_adj)
        assert event.final_confidence == pytest.approx(result.final_confidence)
        assert event.passed_gate == result.passed_gate
        assert event.fingerprint == result.fingerprint


# ---------------------------------------------------------------------------
# Win rate adjustment
# ---------------------------------------------------------------------------

class TestWinRateAdjustment:
    @pytest.mark.asyncio
    async def test_no_data_returns_zero(self) -> None:
        svc = _make_service(repo=_make_repo(win_rate=None))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.win_rate_adj == 0.0

    @pytest.mark.asyncio
    async def test_high_win_rate_gives_positive_adj(self) -> None:
        svc = _make_service(repo=_make_repo(win_rate=0.70))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.win_rate_adj == pytest.approx(_cfg.win_rate.adj_high)

    @pytest.mark.asyncio
    async def test_low_win_rate_gives_negative_adj(self) -> None:
        svc = _make_service(repo=_make_repo(win_rate=0.40))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.win_rate_adj == pytest.approx(_cfg.win_rate.adj_below_low)


# ---------------------------------------------------------------------------
# Regime alignment adjustment
# ---------------------------------------------------------------------------

class TestRegimeAlignmentAdjustment:
    @pytest.mark.asyncio
    async def test_long_in_bullish_gives_positive_adj(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(regime=MarketRegime.TRENDING_BULLISH),
            _make_score_result(direction="LONG"),
            _all_long_outputs(),
        )
        assert result.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_aligned)

    @pytest.mark.asyncio
    async def test_long_in_bearish_gives_large_penalty(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(regime=MarketRegime.TRENDING_BEARISH),
            _make_score_result(direction="LONG"),
            _all_long_outputs(),
        )
        assert result.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_misaligned)

    @pytest.mark.asyncio
    async def test_high_volatility_gives_neutral_adj(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(regime=MarketRegime.HIGH_VOLATILITY),
            _make_score_result(direction="LONG"),
            _all_long_outputs(),
        )
        assert result.regime_alignment_adj == pytest.approx(_cfg.regime_alignment.adj_neutral)


# ---------------------------------------------------------------------------
# Data quality adjustment (redesigned 3-part composite)
# ---------------------------------------------------------------------------

class TestDataQualityAdjustment:
    @pytest.mark.asyncio
    async def test_high_quality_fresh_data_gives_adj_high(self) -> None:
        svc = _make_service()
        outputs = _all_long_outputs(freshness=10)
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            outputs,
        )
        assert result.data_quality_adj == pytest.approx(_cfg.data_quality.adj_high)

    @pytest.mark.asyncio
    async def test_insufficient_quality_low_completeness_gives_penalty(self) -> None:
        svc = _make_service()
        outputs = _all_long_outputs(freshness=500)  # all severely stale
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="INSUFFICIENT", data_completeness_pct=20.0),
            outputs,
        )
        assert result.data_quality_adj <= _cfg.data_quality.adj_mid

    @pytest.mark.asyncio
    async def test_oi_grace_period_exempt_from_freshness_deduction(self) -> None:
        svc = _make_service()
        outputs = [
            _make_component("OI_BUILDUP", 25, freshness=200),  # within grace (300s) → exempt
            _make_component("TREND", 20, freshness=10),
            _make_component("OPTION_CHAIN", 20, freshness=10),
            _make_component("VOLUME", 15, freshness=10),
            _make_component("VWAP", 10, freshness=10),
            _make_component("SENTIMENT", 5, freshness=10),
            _make_component("IV_ANALYSIS", 5, freshness=10),
        ]
        result_with_grace = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            outputs,
        )
        outputs_no_grace = [
            _make_component("OI_BUILDUP", 25, freshness=400),  # beyond grace → penalised
            *outputs[1:],
        ]
        result_no_grace = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            outputs_no_grace,
        )
        assert result_with_grace.data_quality_adj >= result_no_grace.data_quality_adj

    @pytest.mark.asyncio
    async def test_score_quality_drives_composite(self) -> None:
        svc = _make_service()
        outputs = _all_long_outputs(freshness=10)
        result_high = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="HIGH", data_completeness_pct=100.0),
            outputs,
        )
        result_low = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="INSUFFICIENT", data_completeness_pct=100.0),
            outputs,
        )
        # Higher score quality → higher or equal composite → higher or equal adj
        assert result_high.data_quality_adj >= result_low.data_quality_adj

    @pytest.mark.asyncio
    async def test_sub_inputs_recorded_in_components(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(score_quality="MEDIUM", data_completeness_pct=85.0),
            _all_long_outputs(freshness=10),
        )
        assert "dq_composite" in result.confidence_components
        assert "dq_freshness_score" in result.confidence_components
        assert 0.0 <= result.confidence_components["dq_composite"] <= 100.0


# ---------------------------------------------------------------------------
# Signal agreement adjustment
# ---------------------------------------------------------------------------

class TestSignalAgreementAdjustment:
    @pytest.mark.asyncio
    async def test_all_components_agree_gives_adj_high(self) -> None:
        svc = _make_service()
        outputs = _all_long_outputs()  # all LONG
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(direction="LONG"),
            outputs,
        )
        # 7/7 agree → 100% → adj_high
        assert result.signal_agreement_adj == pytest.approx(_cfg.signal_agreement.adj_high)

    @pytest.mark.asyncio
    async def test_all_components_disagree_gives_adj_below_low(self) -> None:
        svc = _make_service()
        outputs = [
            _make_component("OI_BUILDUP", 25, direction="SHORT"),
            _make_component("TREND", 20, direction="SHORT"),
            _make_component("OPTION_CHAIN", 20, direction="SHORT"),
            _make_component("VOLUME", 15, direction="SHORT"),
            _make_component("VWAP", 10, direction="SHORT"),
            _make_component("SENTIMENT", 5, direction="SHORT"),
            _make_component("IV_ANALYSIS", 5, direction="SHORT"),
        ]
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(direction="LONG"),  # score says LONG but all SHORT
            outputs,
        )
        # 0/7 agree → 0% → adj_below_low
        assert result.signal_agreement_adj == pytest.approx(_cfg.signal_agreement.adj_below_low)

    @pytest.mark.asyncio
    async def test_no_available_components_gives_zero(self) -> None:
        svc = _make_service()
        outputs = [
            _make_component(name, w, is_available=False)
            for name, w in [
                ("OI_BUILDUP", 25), ("TREND", 20), ("OPTION_CHAIN", 20),
                ("VOLUME", 15), ("VWAP", 10), ("SENTIMENT", 5), ("IV_ANALYSIS", 5),
            ]
        ]
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), outputs
        )
        assert result.signal_agreement_adj == 0.0

    @pytest.mark.asyncio
    async def test_agreement_pct_recorded_in_components(self) -> None:
        svc = _make_service()
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(direction="LONG"), _all_long_outputs()
        )
        assert result.confidence_components["sa_pct"] == pytest.approx(100.0)
        assert result.confidence_components["sa_agreeing"] == 7.0
        assert result.confidence_components["sa_available"] == 7.0


# ---------------------------------------------------------------------------
# Recent performance adjustment
# ---------------------------------------------------------------------------

class TestRecentPerformanceAdjustment:
    @pytest.mark.asyncio
    async def test_no_history_returns_zero(self) -> None:
        svc = _make_service(repo=_make_repo(recent_outcomes=[]))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.recent_performance_adj == 0.0

    @pytest.mark.asyncio
    async def test_all_wins_gives_adj_high(self) -> None:
        repo = _make_repo(recent_outcomes=["WIN"] * 20)
        svc = _make_service(repo=repo)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_high)

    @pytest.mark.asyncio
    async def test_all_losses_gives_adj_below_low(self) -> None:
        repo = _make_repo(recent_outcomes=["LOSS"] * 20)
        svc = _make_service(repo=repo)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.recent_performance_adj == pytest.approx(_cfg.recent_performance.adj_below_low)

    @pytest.mark.asyncio
    async def test_win_pct_recorded_in_components(self) -> None:
        repo = _make_repo(recent_outcomes=["WIN"] * 10 + ["LOSS"] * 10)
        svc = _make_service(repo=repo)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert "rp_short_win_pct" in result.confidence_components
        assert "rp_long_win_pct" in result.confidence_components
        assert "rp_combined_pct" in result.confidence_components


# ---------------------------------------------------------------------------
# Loss streak adjustment
# ---------------------------------------------------------------------------

class TestLossStreakAdjustment:
    @pytest.mark.asyncio
    async def test_no_streak_no_penalty(self) -> None:
        svc = _make_service(repo=_make_repo(consecutive_losses=0))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.loss_streak_adj == 0.0

    @pytest.mark.asyncio
    async def test_streak_of_3_gives_minus_9(self) -> None:
        svc = _make_service(repo=_make_repo(consecutive_losses=3))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        expected = max(_cfg.loss_streak.floor, _cfg.loss_streak.adj_per_loss * 3)
        assert result.loss_streak_adj == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_large_streak_floored(self) -> None:
        svc = _make_service(repo=_make_repo(consecutive_losses=100))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.loss_streak_adj == pytest.approx(_cfg.loss_streak.floor)


# ---------------------------------------------------------------------------
# Historical accuracy adjustment
# ---------------------------------------------------------------------------

class TestHistoricalAccuracyAdjustment:
    @pytest.mark.asyncio
    async def test_no_history_returns_neutral(self) -> None:
        svc = _make_service(repo=_make_repo(historical_accuracy=None))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.historical_accuracy_adj == pytest.approx(
            _cfg.historical_accuracy.adj_neutral
        )

    @pytest.mark.asyncio
    async def test_high_accuracy_full_samples_gives_max_adj(self) -> None:
        svc = _make_service(repo=_make_repo(historical_accuracy=(0.75, 35)))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.historical_accuracy_adj == pytest.approx(
            _cfg.historical_accuracy.adj_high_full
        )

    @pytest.mark.asyncio
    async def test_low_accuracy_full_samples_gives_max_negative(self) -> None:
        svc = _make_service(repo=_make_repo(historical_accuracy=(0.40, 35)))
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.historical_accuracy_adj == pytest.approx(
            _cfg.historical_accuracy.adj_low_full
        )

    @pytest.mark.asyncio
    async def test_historical_accuracy_called_with_lookback_days(self) -> None:
        repo = _make_repo(historical_accuracy=None)
        svc = _make_service(repo=repo)
        await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        _, kwargs = repo.get_historical_accuracy.call_args
        assert "lookback_days" in kwargs
        assert kwargs["lookback_days"] == _cfg.historical_accuracy.lookback_days


# ---------------------------------------------------------------------------
# Calibration and ceiling
# ---------------------------------------------------------------------------

class TestCalibrationAndCeiling:
    @pytest.mark.asyncio
    async def test_calibration_factor_reduces_confidence(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = "0.9"
        svc = _make_service(redis=redis)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(adjusted_score=80.0), _all_long_outputs()
        )
        assert result.calibrated_confidence <= result.raw_confidence

    @pytest.mark.asyncio
    async def test_calibration_redis_failure_defaults_to_1(self) -> None:
        redis = AsyncMock()
        redis.get.side_effect = Exception("Redis down")
        svc = _make_service(redis=redis)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(), _all_long_outputs()
        )
        assert result.calibrated_confidence == pytest.approx(result.raw_confidence, abs=0.01)

    @pytest.mark.asyncio
    async def test_standard_score_band_ceiling_applied(self) -> None:
        repo = _make_repo(win_rate=0.80, historical_accuracy=(0.80, 50))
        svc = _make_service(repo=repo)
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(adjusted_score=75.0),
            _all_long_outputs(),
        )
        assert result.final_confidence <= _cfg.ceiling.standard_max_confidence

    @pytest.mark.asyncio
    async def test_strong_score_band_uncapped(self) -> None:
        svc = _make_service(repo=_make_repo(win_rate=0.80, historical_accuracy=(0.80, 50)))
        result = await svc.calculate_confidence(
            _make_context(),
            _make_score_result(adjusted_score=90.0),
            _all_long_outputs(),
        )
        assert result.score_bucket == "STRONG"

    @pytest.mark.asyncio
    async def test_final_confidence_always_clamped(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = "2.0"  # 200% factor — must not exceed 100
        svc = _make_service(redis=redis)
        result = await svc.calculate_confidence(
            _make_context(), _make_score_result(adjusted_score=90.0), _all_long_outputs()
        )
        assert 0.0 <= result.final_confidence <= 100.0  # AC-12
