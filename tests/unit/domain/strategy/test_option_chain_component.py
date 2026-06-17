"""Unit tests for OptionChainComponent."""

from __future__ import annotations

from core.domain.strategy.option_chain_component import OptionChainComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features, _oc

_cfg = load_strategy_config()


def _comp() -> OptionChainComponent:
    return OptionChainComponent(_cfg)


class TestOptionChainIdentity:
    def test_component_name(self) -> None:
        assert _comp().component_name == "OPTION_CHAIN"

    def test_max_weight(self) -> None:
        assert _comp().max_weight == 20


class TestOptionChainUnavailable:
    def test_no_iv_pct_returns_unavailable(self) -> None:
        out = _comp().evaluate(_ctx(features=_features()))
        assert not out.is_available

    def test_is_available_when_features_has_iv_pct(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.is_available


class TestOptionChainIVLong:
    def test_low_iv_benefits_long(self) -> None:
        out_low = _comp().evaluate(_ctx(features=_features(iv_percentile=10.0)))
        out_high = _comp().evaluate(_ctx(features=_features(iv_percentile=80.0)))
        assert out_low.long_score > out_high.long_score

    def test_very_high_iv_gives_zero_long_iv_score(self) -> None:
        # iv_pct > 75 → long_score_tier_5 = 0; only skew/gex/wall can add
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=90.0)))
        # With no option chain data, wall/skew/gex all = 0, PCR = 0
        # long_score should come only from base tier = 0
        assert out.long_score < out.short_score or out.long_score == 0.0


class TestOptionChainIVShort:
    def test_high_iv_benefits_short(self) -> None:
        out_high = _comp().evaluate(_ctx(features=_features(iv_percentile=80.0)))
        out_low = _comp().evaluate(_ctx(features=_features(iv_percentile=10.0)))
        assert out_high.short_score > out_low.short_score


class TestOptionChainSkew:
    def test_negative_skew_benefits_long(self) -> None:
        # put_iv < call_iv → calls expensive → bullish demand → LONG
        out_neg = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(iv_skew=-2.0),
        ))
        out_no_skew = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out_neg.long_score > out_no_skew.long_score

    def test_positive_skew_benefits_short(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(iv_skew=2.0),
        ))
        out_no_skew = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.short_score > out_no_skew.short_score

    def test_neutral_skew_no_effect(self) -> None:
        out_neutral = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(iv_skew=0.5),  # < threshold
        ))
        out_no_oc = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out_neutral.long_score == out_no_oc.long_score


class TestOptionChainOIWalls:
    def test_far_call_wall_benefits_long(self) -> None:
        out_far = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(nearest_call_wall_distance_pct=2.5),
        ))
        out_close = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(nearest_call_wall_distance_pct=0.3),
        ))
        assert out_far.long_score > out_close.long_score

    def test_close_call_wall_penalizes_long(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(nearest_call_wall_distance_pct=0.3),
        ))
        out_no_wall = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.long_score < out_no_wall.long_score


class TestOptionChainPCRTrend:
    def test_rising_pcr_benefits_long(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(pcr_trend="RISING"),
        ))
        out_no_pcr = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.long_score > out_no_pcr.long_score

    def test_falling_pcr_benefits_short(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=30.0),
            option_chain=_oc(pcr_trend="FALLING"),
        ))
        out_no_pcr = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.short_score > out_no_pcr.short_score


class TestOptionChainScoreBounds:
    def test_scores_capped_at_max_weight(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=5.0),
            option_chain=_oc(
                iv_skew=-5.0,
                gex_positive=False,
                nearest_call_wall_distance_pct=3.0,
                nearest_put_wall_distance_pct=3.0,
                pcr_trend="RISING",
            ),
        ))
        assert out.long_score <= 20.0
        assert out.short_score <= 20.0

    def test_scores_non_negative(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(iv_percentile=90.0),
            option_chain=_oc(
                iv_skew=5.0,
                nearest_call_wall_distance_pct=0.1,
                pcr_trend="FALLING",
            ),
        ))
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0
