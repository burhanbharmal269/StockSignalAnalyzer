"""Unit tests for OIBuildupComponent."""

from __future__ import annotations

from core.domain.strategy.oi_buildup_component import OIBuildupComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features

_cfg = load_strategy_config()


def _oi(**kwargs) -> OIBuildupComponent:
    return OIBuildupComponent(_cfg)


class TestOIBuildupUnavailable:
    def test_missing_oi_change_pct_returns_unavailable(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), price_change_pct=0.5)
        out = comp.evaluate(ctx)
        assert not out.is_available
        assert out.long_score == 0.0
        assert out.short_score == 0.0

    def test_missing_price_change_pct_returns_unavailable(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=3.0)
        out = comp.evaluate(ctx)
        assert not out.is_available

    def test_component_name(self) -> None:
        assert _oi().component_name == "OI_BUILDUP"

    def test_max_weight(self) -> None:
        assert _oi().max_weight == 25


class TestOIBuildupLongBuildup:
    def test_long_buildup_gives_long_score(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        out = comp.evaluate(ctx)
        assert out.is_available
        assert out.long_score > out.short_score
        assert out.direction == "LONG"

    def test_long_buildup_score_capped_at_25(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=50.0, price_change_pct=5.0)
        out = comp.evaluate(ctx)
        assert out.long_score <= 25.0

    def test_long_buildup_short_score_is_zero(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        out = comp.evaluate(ctx)
        assert out.short_score == 0.0

    def test_conviction_proportional_to_score(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=10.0, price_change_pct=1.0)
        out = comp.evaluate(ctx)
        assert 0.0 < out.conviction <= 1.0


class TestOIBuildupShortBuildup:
    def test_short_buildup_gives_short_score(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=-0.5)
        out = comp.evaluate(ctx)
        assert out.short_score > out.long_score
        assert out.direction == "SHORT"

    def test_short_buildup_long_score_is_zero(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=-0.5)
        out = comp.evaluate(ctx)
        assert out.long_score == 0.0


class TestOIBuildupWeakSignals:
    def test_short_covering_gives_long_direction(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=-3.0, price_change_pct=0.5)
        out = comp.evaluate(ctx)
        assert out.direction == "LONG"
        assert out.long_score <= 15.0  # capped at max_weak_score

    def test_long_unwinding_gives_short_direction(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=-3.0, price_change_pct=-0.5)
        out = comp.evaluate(ctx)
        assert out.direction == "SHORT"

    def test_ambiguous_splits_evenly(self) -> None:
        comp = _oi()
        ctx = _ctx(features=_features(), oi_change_pct=0.5, price_change_pct=0.1)
        out = comp.evaluate(ctx)
        assert out.direction == "NEUTRAL"
        assert out.long_score == out.short_score
        assert out.long_score > 0  # ambiguous floor


class TestOIBuildupPCRAdjustment:
    def test_high_pcr_adds_long_score(self) -> None:
        comp = _oi()
        base = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        with_pcr = _ctx(
            features=_features(pcr=1.5),  # > pcr_strong_bullish
            oi_change_pct=4.0,
            price_change_pct=0.5,
        )
        assert with_pcr.features.pcr is not None
        out_base = comp.evaluate(base)
        out_pcr = comp.evaluate(with_pcr)
        assert out_pcr.long_score > out_base.long_score

    def test_low_pcr_reduces_long_score(self) -> None:
        comp = _oi()
        with_low_pcr = _ctx(
            features=_features(pcr=0.5),  # < pcr_bullish_low
            oi_change_pct=4.0,
            price_change_pct=0.5,
        )
        without_pcr = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        out_low = comp.evaluate(with_low_pcr)
        out_no = comp.evaluate(without_pcr)
        assert out_low.long_score < out_no.long_score


class TestOIBuildupFIIAdjustment:
    def test_fii_long_adds_to_long_score(self) -> None:
        comp = _oi()
        ctx = _ctx(
            features=_features(),
            oi_change_pct=4.0,
            price_change_pct=0.5,
            fii_net_contracts=10000,
        )
        ctx_no_fii = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        assert comp.evaluate(ctx).long_score > comp.evaluate(ctx_no_fii).long_score

    def test_fii_neutral_has_no_effect(self) -> None:
        comp = _oi()
        ctx = _ctx(
            features=_features(),
            oi_change_pct=4.0,
            price_change_pct=0.5,
            fii_net_contracts=1000,  # below threshold
        )
        ctx_none = _ctx(features=_features(), oi_change_pct=4.0, price_change_pct=0.5)
        assert comp.evaluate(ctx).long_score == comp.evaluate(ctx_none).long_score


class TestOIBuildupScoreBounds:
    def test_long_score_never_exceeds_max_weight(self) -> None:
        comp = _oi()
        ctx = _ctx(
            features=_features(pcr=2.0),
            oi_change_pct=100.0,
            price_change_pct=10.0,
            fii_net_contracts=100000,
            max_pain_price=22000.0,
        )
        out = comp.evaluate(ctx)
        assert out.long_score <= 25.0
        assert out.short_score <= 25.0

    def test_scores_always_non_negative(self) -> None:
        comp = _oi()
        ctx = _ctx(
            features=_features(pcr=0.3),
            oi_change_pct=-10.0,
            price_change_pct=-2.0,
            fii_net_contracts=-50000,
        )
        out = comp.evaluate(ctx)
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0
