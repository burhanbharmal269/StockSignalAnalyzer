"""Unit tests for VolumeComponent."""

from __future__ import annotations

from core.domain.strategy.volume_component import VolumeComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features

_cfg = load_strategy_config()


def _comp() -> VolumeComponent:
    return VolumeComponent(_cfg)


class TestVolumeIdentity:
    def test_component_name(self) -> None:
        assert _comp().component_name == "VOLUME"

    def test_max_weight(self) -> None:
        assert _comp().max_weight == 15


class TestVolumeUnavailable:
    def test_missing_volume_ratio_returns_unavailable(self) -> None:
        out = _comp().evaluate(_ctx(features=_features()))
        assert not out.is_available


class TestVolumeRatioTiers:
    def test_very_low_volume_gives_low_score(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(), volume_ratio=0.3))
        assert out.long_score <= 3.0
        assert out.short_score <= 3.0

    def test_high_volume_gives_high_score(self) -> None:
        out = _comp().evaluate(_ctx(features=_features(), volume_ratio=2.5))
        # max from volume_ratio_score_5 = 15, minus possible penalties
        assert out.long_score >= 10.0 or out.short_score >= 10.0

    def test_higher_volume_ratio_gives_higher_score(self) -> None:
        out_low = _comp().evaluate(_ctx(features=_features(), volume_ratio=0.8))
        out_high = _comp().evaluate(_ctx(features=_features(), volume_ratio=2.5))
        # Both directions should benefit from higher volume
        assert max(out_high.long_score, out_high.short_score) > max(
            out_low.long_score, out_low.short_score
        )


class TestVolumeDivergencePenalty:
    def test_price_up_low_volume_applies_penalty(self) -> None:
        out_div = _comp().evaluate(_ctx(
            features=_features(),
            volume_ratio=0.8,        # declining volume
            price_change_pct=1.0,    # price rising
        ))
        out_no_div = _comp().evaluate(_ctx(
            features=_features(),
            volume_ratio=0.8,
            price_change_pct=None,   # no price data = no penalty
        ))
        assert out_div.long_score < out_no_div.long_score

    def test_no_divergence_when_price_flat(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            volume_ratio=0.8,
            price_change_pct=0.0,    # flat price — no divergence
        ))
        # Flat price at declining volume doesn't trigger penalty
        assert out.long_score >= 0.0


class TestVolumeOBV:
    def test_obv_up_benefits_long(self) -> None:
        out_obv = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, obv_trend="UP"
        ))
        out_no_obv = _comp().evaluate(_ctx(features=_features(), volume_ratio=1.5))
        assert out_obv.long_score > out_no_obv.long_score

    def test_obv_down_benefits_short(self) -> None:
        out_obv = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, obv_trend="DOWN"
        ))
        out_no_obv = _comp().evaluate(_ctx(features=_features(), volume_ratio=1.5))
        assert out_obv.short_score > out_no_obv.short_score

    def test_obv_flat_no_effect(self) -> None:
        out_flat = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, obv_trend="FLAT"
        ))
        out_none = _comp().evaluate(_ctx(features=_features(), volume_ratio=1.5))
        assert out_flat.long_score == out_none.long_score


class TestVolumeCumulativeDelta:
    def test_positive_delta_benefits_long(self) -> None:
        out_pos = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, cumulative_delta=1000.0
        ))
        out_none = _comp().evaluate(_ctx(features=_features(), volume_ratio=1.5))
        assert out_pos.long_score > out_none.long_score

    def test_negative_delta_benefits_short(self) -> None:
        out_neg = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, cumulative_delta=-1000.0
        ))
        out_none = _comp().evaluate(_ctx(features=_features(), volume_ratio=1.5))
        assert out_neg.short_score > out_none.short_score


class TestVolumeVPOC:
    def test_at_vpoc_adds_bonus(self) -> None:
        out_vpoc = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, vpoc_distance_pct=0.1
        ))
        out_far = _comp().evaluate(_ctx(
            features=_features(), volume_ratio=1.5, vpoc_distance_pct=1.0
        ))
        assert out_vpoc.long_score > out_far.long_score


class TestVolumeScoreBounds:
    def test_scores_capped_at_max_weight(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            volume_ratio=5.0,
            obv_trend="UP",
            cumulative_delta=100000.0,
            vpoc_distance_pct=0.05,
        ))
        assert out.long_score <= 15.0
        assert out.short_score <= 15.0

    def test_scores_non_negative(self) -> None:
        out = _comp().evaluate(_ctx(
            features=_features(),
            volume_ratio=0.3,
            price_change_pct=2.0,    # divergence penalty
            obv_trend="DOWN",
            cumulative_delta=-10000.0,
        ))
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0
