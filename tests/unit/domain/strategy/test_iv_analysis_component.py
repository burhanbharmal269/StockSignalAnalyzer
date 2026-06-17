"""Unit tests for IVAnalysisComponent."""

from __future__ import annotations

from core.domain.strategy.iv_analysis_component import IVAnalysisComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features

_cfg = load_strategy_config()


def _comp() -> IVAnalysisComponent:
    return IVAnalysisComponent(_cfg)


class TestIVIdentity:
    def test_component_name(self) -> None:
        assert _comp().component_name == "IV_ANALYSIS"

    def test_max_weight(self) -> None:
        assert _comp().max_weight == 5


class TestIVUnavailable:
    def test_missing_iv_pct_returns_unavailable(self) -> None:
        out = _comp().evaluate(_ctx(features=_features()))
        assert not out.is_available


class TestIVLongVolScore:
    def test_low_iv_max_long_score(self) -> None:
        # iv_pct < 20 → buy_score_max = 5
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=10.0)))
        assert out.long_score == 5.0

    def test_moderate_iv_mid_long_score(self) -> None:
        # iv_pct 20-35 → buy_score_mid = 3
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=28.0)))
        assert out.long_score == 3.0

    def test_low_range_iv_gives_long_score_low(self) -> None:
        # iv_pct 35-50 → buy_score_low = 1
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=42.0)))
        assert out.long_score == 1.0

    def test_high_iv_zero_long_score(self) -> None:
        # iv_pct > 50 → 0
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=60.0)))
        assert out.long_score == 0.0


class TestIVShortVolScore:
    def test_very_high_iv_max_short_score(self) -> None:
        # iv_pct >= 70 → sell_score_max = 5
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=80.0)))
        assert out.short_score == 5.0

    def test_mid_high_iv_mid_short_score(self) -> None:
        # iv_pct 55-70 → sell_score_mid = 3
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=62.0)))
        assert out.short_score == 3.0

    def test_mid_iv_low_short_score(self) -> None:
        # iv_pct 40-55 → sell_score_low = 1
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=47.0)))
        assert out.short_score == 1.0

    def test_low_iv_zero_short_score(self) -> None:
        # iv_pct < 40 → 0
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.short_score == 0.0


class TestIVHVIVBonus:
    def test_high_hv_iv_ratio_boosts_long(self) -> None:
        # Use iv_pct=28 (base=3) so hv_iv bonus of +2 makes a visible difference
        out_bonus = _comp().evaluate(_ctx(features=_features(
            iv_percentile=28.0, hv_iv_ratio=1.5
        )))
        out_no_bonus = _comp().evaluate(_ctx(features=_features(iv_percentile=28.0)))
        assert out_bonus.long_score > out_no_bonus.long_score

    def test_low_hv_iv_ratio_boosts_short(self) -> None:
        # Use iv_pct=62 (base=3) so hv_iv bonus of +2 makes a visible difference
        out_bonus = _comp().evaluate(_ctx(features=_features(
            iv_percentile=62.0, hv_iv_ratio=0.6
        )))
        out_no_bonus = _comp().evaluate(_ctx(features=_features(iv_percentile=62.0)))
        assert out_bonus.short_score > out_no_bonus.short_score

    def test_neutral_hv_iv_no_bonus(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(
            iv_percentile=30.0, hv_iv_ratio=1.0
        )))
        out_none = _comp().evaluate(_ctx(features=_features(iv_percentile=30.0)))
        assert out.long_score == out_none.long_score


class TestIVVIXPenalty:
    def test_high_vix_penalizes_short_vol(self) -> None:
        # VIX > 20 applies penalty to short_score
        out_high_vix = _comp().evaluate(_ctx(features=_features(
            iv_percentile=75.0, india_vix=25.0
        )))
        out_low_vix = _comp().evaluate(_ctx(features=_features(
            iv_percentile=75.0, india_vix=15.0
        )))
        assert out_high_vix.short_score < out_low_vix.short_score

    def test_vix_penalty_does_not_affect_long_score(self) -> None:
        out_high_vix = _comp().evaluate(_ctx(features=_features(
            iv_percentile=10.0, india_vix=25.0
        )))
        out_low_vix = _comp().evaluate(_ctx(features=_features(
            iv_percentile=10.0, india_vix=15.0
        )))
        assert out_high_vix.long_score == out_low_vix.long_score


class TestIVScoreBounds:
    def test_scores_capped_at_max_weight(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(
            iv_percentile=5.0, hv_iv_ratio=2.0
        )))
        assert out.long_score <= 5.0

    def test_scores_non_negative(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(
            iv_percentile=80.0, india_vix=30.0, hv_iv_ratio=0.5
        )))
        assert out.short_score >= 0.0
        assert out.long_score >= 0.0

    def test_direction_reflects_dominant_side(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=10.0)))
        assert out.direction == "LONG"

    def test_high_iv_direction_is_short(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(iv_percentile=80.0)))
        assert out.direction == "SHORT"
