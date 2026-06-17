"""Unit tests for RegimeEvaluationUseCase."""

from __future__ import annotations

from core.application.use_cases.regime_evaluation_use_case import RegimeEvaluationUseCase
from core.domain.enums.market_regime import MarketRegime
from core.domain.regime.confidence_calculator import ConfidenceCalculator
from core.domain.regime.regime_resolver import RegimeResolver
from core.domain.regime.trend_layer import TrendLayer
from core.domain.regime.volatility_layer import VolatilityLayer
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()


def _make_use_case() -> RegimeEvaluationUseCase:
    return RegimeEvaluationUseCase(
        trend_layer=TrendLayer(_cfg),
        volatility_layer=VolatilityLayer(_cfg),
        resolver=RegimeResolver(_cfg),
        confidence_calculator=ConfidenceCalculator(_cfg),
    )


def _snap(**kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": 256265, "timeframe": "15m", **kwargs})


class TestRegimeEvaluationUseCaseOutput:
    def test_returns_regime_snapshot(self) -> None:
        from core.domain.value_objects.regime_snapshot import RegimeSnapshot

        uc = _make_use_case()
        snap = _snap(india_vix=30.0)
        result = uc.execute(snap)
        assert isinstance(result, RegimeSnapshot)

    def test_instrument_token_passed_through(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(instrument_token=99))
        assert result.instrument_token == 99

    def test_timeframe_passed_through(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(timeframe="5m"))
        assert result.timeframe == "5m"

    def test_confidence_in_valid_range(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(india_vix=18.0, adx=30.0, di_plus=35.0, di_minus=15.0))
        assert 0 <= result.confidence <= 100

    def test_unsmoothed_stability_is_zero(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap())
        assert result.stability_score == 0.0

    def test_unsmoothed_duration_is_zero(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap())
        assert result.regime_duration_bars == 0

    def test_unsmoothed_transition_is_false(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap())
        assert result.transition_signal is False


class TestRegimeEvaluationUseCaseRegimes:
    def test_panic_vix_produces_high_volatility(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(india_vix=30.0))
        assert result.primary_regime == MarketRegime.HIGH_VOLATILITY

    def test_strong_trending_bullish(self) -> None:
        uc = _make_use_case()
        result = uc.execute(
            _snap(india_vix=18.0, adx=32.0, di_plus=40.0, di_minus=15.0)
        )
        assert result.primary_regime == MarketRegime.TRENDING_BULLISH

    def test_strong_trending_bearish(self) -> None:
        uc = _make_use_case()
        result = uc.execute(
            _snap(india_vix=18.0, adx=32.0, di_plus=15.0, di_minus=40.0)
        )
        assert result.primary_regime == MarketRegime.TRENDING_BEARISH

    def test_no_indicators_produces_sideways(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap())
        assert result.primary_regime == MarketRegime.SIDEWAYS

    def test_low_vix_produces_low_volatility(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(india_vix=11.0, atr_ratio=0.6))
        assert result.primary_regime == MarketRegime.LOW_VOLATILITY

    def test_explanation_is_tuple(self) -> None:
        uc = _make_use_case()
        result = uc.execute(_snap(india_vix=18.0, adx=30.0))
        assert isinstance(result.explanation, tuple)
