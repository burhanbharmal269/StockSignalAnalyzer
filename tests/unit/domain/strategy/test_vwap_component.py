"""Unit tests for VWAPComponent."""

from __future__ import annotations

from core.domain.enums.market_regime import MarketRegime
from core.domain.strategy.vwap_component import VWAPComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features

_cfg = load_strategy_config()


def _comp() -> VWAPComponent:
    return VWAPComponent(_cfg)


class TestVWAPIdentity:
    def test_component_name(self) -> None:
        assert _comp().component_name == "VWAP"

    def test_max_weight(self) -> None:
        assert _comp().max_weight == 10


class TestVWAPUnavailable:
    def test_missing_sigma_returns_unavailable(self) -> None:
        out = _comp().evaluate(_ctx(features=_features()))
        assert not out.is_available


class TestVWAPModeA:
    def test_price_deep_below_vwap_gives_long_score(self) -> None:
        # -2σ with good volume and RSI oversold
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-2.0,
            volume_ratio=1.8,
            rsi_14=30.0,
        ))
        assert out.long_score > out.short_score
        assert out.direction == "LONG"

    def test_price_deep_above_vwap_gives_short_score(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=2.0,
            volume_ratio=1.8,
            rsi_14=70.0,  # above rsi_short_extreme=65
        ))
        assert out.short_score > out.long_score
        assert out.direction == "SHORT"

    def test_price_at_vwap_gives_zero_in_mode_a(self) -> None:
        # sigma = 0 → no deviation → no mean-reversion opportunity
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=0.0,
            volume_ratio=1.5,
            rsi_14=50.0,
        ))
        assert out.long_score == 0.0
        assert out.short_score == 0.0

    def test_touch_count_degrades_score(self) -> None:
        out_fresh = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-1.5,
            volume_ratio=1.8,
            rsi_14=30.0,
            vwap_touch_count=0,
        ))
        out_exhausted = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-1.5,
            volume_ratio=1.8,
            rsi_14=30.0,
            vwap_touch_count=3,
        ))
        assert out_fresh.long_score > out_exhausted.long_score

    def test_moderate_deviation_gives_partial_score(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-0.6,
            rsi_14=48.0,
        ))
        assert 0 < out.long_score < 10.0

    def test_insufficient_volume_in_mode_a_no_extreme_score(self) -> None:
        # At -2σ but volume too low for extreme setup
        out_low_vol = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-2.0,
            volume_ratio=1.0,   # below mode_a_volume_ratio_extreme=1.5
            rsi_14=30.0,
        ))
        out_high_vol = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-2.0,
            volume_ratio=1.8,
            rsi_14=30.0,
        ))
        assert out_high_vol.long_score > out_low_vol.long_score


class TestVWAPModeB:
    def test_price_above_vwap_in_trending_gives_long(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.TRENDING_BULLISH,
            features=_features(),
            vwap_deviation_sigma=1.0,
        ))
        assert out.long_score >= out.short_score

    def test_price_below_vwap_in_trending_gives_short(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.TRENDING_BEARISH,
            features=_features(),
            vwap_deviation_sigma=-1.0,
        ))
        assert out.short_score >= out.long_score

    def test_near_vwap_in_trending_gives_max_score(self) -> None:
        # Near VWAP (within bounce_proximity_sigma) = possible bounce
        out_near = _comp().evaluate(_ctx(
            regime=MarketRegime.TRENDING_BULLISH,
            features=_features(),
            vwap_deviation_sigma=0.2,  # within mode_b_bounce_proximity_sigma=0.3
        ))
        out_far = _comp().evaluate(_ctx(
            regime=MarketRegime.TRENDING_BULLISH,
            features=_features(),
            vwap_deviation_sigma=2.0,
        ))
        assert out_near.long_score >= out_far.long_score

    def test_high_vol_uses_mode_a(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.HIGH_VOLATILITY,
            features=_features(),
            vwap_deviation_sigma=-1.5,
            volume_ratio=1.8,
            rsi_14=30.0,
        ))
        assert out.long_score > 0


class TestVWAPScoreBounds:
    def test_long_score_capped_at_max_weight(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.SIDEWAYS,
            features=_features(),
            vwap_deviation_sigma=-3.0,
            volume_ratio=5.0,
            rsi_14=10.0,
        ))
        assert out.long_score <= 10.0

    def test_scores_non_negative(self) -> None:
        out = _comp().evaluate(_ctx(
            regime=MarketRegime.TRENDING_BULLISH,
            features=_features(),
            vwap_deviation_sigma=-5.0,
        ))
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0
