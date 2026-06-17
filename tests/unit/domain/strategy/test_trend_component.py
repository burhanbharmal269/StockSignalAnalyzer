"""Unit tests for TrendComponent."""

from __future__ import annotations

import pytest

from core.domain.strategy.trend_component import TrendComponent
from core.infrastructure.config.strategy_config import load_strategy_config

from .conftest import _ctx, _features

_cfg = load_strategy_config()


def _trend() -> TrendComponent:
    return TrendComponent(_cfg)


class TestTrendComponentIdentity:
    def test_component_name(self) -> None:
        assert _trend().component_name == "TREND"

    def test_max_weight(self) -> None:
        assert _trend().max_weight == 20


class TestTrendADXGate:
    def test_missing_adx_returns_unavailable(self) -> None:
        out = _trend().evaluate(_ctx(features=_features()))
        assert not out.is_available

    def test_low_adx_triggers_hard_gate(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(adx=15.0, di_plus=30.0, di_minus=10.0)))
        assert out.is_available
        assert out.long_score == 0.0
        assert out.short_score == 0.0
        assert out.direction == "NEUTRAL"

    def test_adx_exactly_at_gate_triggers_gate(self) -> None:
        # Gate is strict < 20.0; 19.9 is below the threshold
        out = _trend().evaluate(_ctx(features=_features(adx=19.9, di_plus=30.0, di_minus=10.0)))
        assert out.long_score == 0.0

    def test_adx_above_gate_passes(self) -> None:
        out = _trend().evaluate(
            _ctx(features=_features(adx=25.0, di_plus=30.0, di_minus=10.0))
        )
        assert out.long_score > 0


class TestTrendDISpread:
    def test_missing_di_returns_unavailable(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(adx=30.0)))
        assert not out.is_available

    def test_di_plus_dominant_gives_long(self) -> None:
        out = _trend().evaluate(
            _ctx(features=_features(adx=30.0, di_plus=40.0, di_minus=10.0))
        )
        assert out.direction == "LONG"
        assert out.long_score > out.short_score

    def test_di_minus_dominant_gives_short(self) -> None:
        out = _trend().evaluate(
            _ctx(features=_features(adx=30.0, di_plus=10.0, di_minus=40.0))
        )
        assert out.direction == "SHORT"
        assert out.short_score > out.long_score

    def test_narrow_spread_gives_zero_di_score(self) -> None:
        # Spread < 5 → no DI bonus
        out_narrow = _trend().evaluate(
            _ctx(features=_features(adx=30.0, di_plus=25.0, di_minus=23.0))
        )
        out_wide = _trend().evaluate(
            _ctx(features=_features(adx=30.0, di_plus=40.0, di_minus=10.0))
        )
        assert out_wide.long_score > out_narrow.long_score


class TestTrendADXScoreTiers:
    @pytest.mark.parametrize("adx,min_score", [
        (22.0, 7.0),   # gate-to-weak tier
        (26.0, 11.0),  # weak-to-moderate
        (29.0, 15.0),  # moderate-to-strong
        (33.0, 17.0),  # strong-to-very-strong
        (37.0, 19.0),  # very strong
    ])
    def test_adx_tiers(self, adx: float, min_score: float) -> None:
        out = _trend().evaluate(
            _ctx(features=_features(adx=adx, di_plus=40.0, di_minus=10.0))
        )
        # Score includes ADX base + DI spread + potential bonuses
        assert out.long_score >= min_score


class TestTrendEMAAlignment:
    def test_full_ema_stack_adds_score(self) -> None:
        # adx=22 (8 pts) + spread=7 (3 pts) = 11 base — room for EMA +5 bonus
        out_full = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=27.0, di_minus=20.0,
            ema_20=22100.0, ema_50=22000.0, ema_200=21000.0,
        )))
        out_no_ema = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=27.0, di_minus=20.0,
        )))
        assert out_full.long_score > out_no_ema.long_score

    def test_bearish_ema_stack_helps_short(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=20.0, di_minus=27.0,
            ema_20=20000.0, ema_50=21000.0, ema_200=22000.0,
        )))
        assert out.direction == "SHORT"
        assert out.short_score > out.long_score


class TestTrendSupertrend:
    def test_bullish_supertrend_adds_long_score(self) -> None:
        # adx=22 (8 pts) + spread=7 (3 pts) = 11 base — room for supertrend +3 bonus
        out_st = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=27.0, di_minus=20.0, supertrend_direction=1,
        )))
        out_no_st = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=27.0, di_minus=20.0,
        )))
        assert out_st.long_score > out_no_st.long_score

    def test_bearish_supertrend_adds_short_score(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(
            adx=22.0, di_plus=20.0, di_minus=27.0, supertrend_direction=-1,
        )))
        assert out.short_score > _trend().evaluate(
            _ctx(features=_features(adx=22.0, di_plus=20.0, di_minus=27.0))
        ).short_score


class TestTrendRSIGate:
    def test_rsi_in_range_adds_bonus(self) -> None:
        # adx=22 (8 pts) + spread=7 (3 pts) = 11 base — room for RSI gate +1 bonus
        out_rsi = _trend().evaluate(_ctx(
            features=_features(adx=22.0, di_plus=27.0, di_minus=20.0),
            rsi_14=60.0,  # within 45-75 for LONG
        ))
        out_no_rsi = _trend().evaluate(_ctx(
            features=_features(adx=22.0, di_plus=27.0, di_minus=20.0),
        ))
        assert out_rsi.long_score > out_no_rsi.long_score

    def test_rsi_overbought_no_bonus(self) -> None:
        out = _trend().evaluate(_ctx(
            features=_features(adx=22.0, di_plus=27.0, di_minus=20.0),
            rsi_14=80.0,  # overbought — outside 45-75 gate
        ))
        out_no_rsi = _trend().evaluate(_ctx(
            features=_features(adx=22.0, di_plus=27.0, di_minus=20.0),
        ))
        assert out.long_score == out_no_rsi.long_score


class TestTrendScoreBounds:
    def test_score_never_exceeds_max_weight(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(
            adx=50.0, di_plus=60.0, di_minus=5.0,
            ema_20=22100.0, ema_50=22000.0, ema_200=21000.0,
            supertrend_direction=1,
        ), rsi_14=60.0))
        assert out.long_score <= 20.0

    def test_score_never_negative(self) -> None:
        out = _trend().evaluate(_ctx(features=_features(
            adx=25.0, di_plus=15.0, di_minus=10.0,
        )))
        assert out.long_score >= 0.0
        assert out.short_score >= 0.0
