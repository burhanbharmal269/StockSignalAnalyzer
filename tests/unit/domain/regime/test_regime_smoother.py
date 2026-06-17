"""Unit tests for RegimeSmoother — α-blending and transition tracking."""

from __future__ import annotations

from core.domain.enums.market_regime import MarketRegime
from core.domain.regime.regime_smoother import RegimeSmoother
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()


def _smoother() -> RegimeSmoother:
    return RegimeSmoother(_cfg)


class TestRegimeSmootherFirstBar:
    def test_first_bar_duration_is_one(self) -> None:
        s = _smoother()
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 80)
        assert result.duration_bars == 1

    def test_first_bar_transition_is_true(self) -> None:
        s = _smoother()
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 80)
        assert result.transition_signal is True

    def test_first_bar_stability_less_than_one(self) -> None:
        s = _smoother()
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 80)
        assert result.stability_score < 1.0

    def test_first_bar_effective_confidence_gt_zero(self) -> None:
        s = _smoother()
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 80)
        assert result.effective_confidence > 0


class TestRegimeSmootherStabilityGrowth:
    def test_stability_increases_with_bars(self) -> None:
        s = _smoother()
        prev_stability = 0.0
        for _ in range(5):
            result = s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
            assert result.stability_score >= prev_stability
            prev_stability = result.stability_score

    def test_stability_caps_at_one(self) -> None:
        s = _smoother()
        for _ in range(20):
            result = s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        assert result.stability_score == 1.0

    def test_duration_increments_per_bar(self) -> None:
        s = _smoother()
        for i in range(1, 6):
            result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 75)
            assert result.duration_bars == i


class TestRegimeSmootherTransition:
    def test_transition_flagged_on_regime_change(self) -> None:
        s = _smoother()
        s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 75)
        assert result.transition_signal is True

    def test_no_transition_on_same_regime(self) -> None:
        s = _smoother()
        s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        result = s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        assert result.transition_signal is False

    def test_duration_resets_on_transition(self) -> None:
        s = _smoother()
        for _ in range(5):
            s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 75)
        assert result.duration_bars == 1

    def test_stability_resets_on_transition(self) -> None:
        s = _smoother()
        for _ in range(20):
            s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 75)
        assert result.stability_score < 1.0


class TestRegimeSmootherMultiKey:
    def test_different_instruments_tracked_independently(self) -> None:
        s = _smoother()
        for _ in range(5):
            s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        result_2 = s.update(2, "15m", MarketRegime.SIDEWAYS, 70)
        result_1 = s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        assert result_1.duration_bars == 6
        assert result_2.duration_bars == 1

    def test_reset_clears_state(self) -> None:
        s = _smoother()
        for _ in range(5):
            s.update(1, "15m", MarketRegime.SIDEWAYS, 70)
        s.reset(1, "15m")
        result = s.update(1, "15m", MarketRegime.TRENDING_BULLISH, 70)
        assert result.duration_bars == 1
        assert result.transition_signal is True


class TestRegimeSmootherHighVol:
    def test_high_vol_min_bars_is_immediate(self) -> None:
        s = _smoother()
        result = s.update(1, "15m", MarketRegime.HIGH_VOLATILITY, 90)
        # min_bars = 1 → stability = 1.0 after first bar
        assert result.stability_score == 1.0
