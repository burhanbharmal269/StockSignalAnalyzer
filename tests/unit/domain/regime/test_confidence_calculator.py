"""Unit tests for ConfidenceCalculator — per-regime scoring tables."""

from __future__ import annotations

from core.domain.enums.market_regime import MarketRegime
from core.domain.regime.confidence_calculator import ConfidenceCalculator
from core.domain.regime.trend_layer import DirectionSignal
from core.domain.regime.volatility_layer import VolatilitySignal
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()
_calc = ConfidenceCalculator(_cfg)


def _snap(**kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": 1, "timeframe": "15m", **kwargs})


def _dir(
    direction: str = "BULLISH",
    adx: float = 30.0,
    spread: float = 15.0,
    gate: bool = True,
) -> DirectionSignal:
    return DirectionSignal(
        direction=direction, adx_strength=adx, di_spread=spread, is_gate_open=gate
    )


def _vol(
    level: str = "NORMAL",
    vix: float = 18.0,
    atr: float = 1.0,
    panic: bool = False,
) -> VolatilitySignal:
    return VolatilitySignal(
        level=level, vix_value=vix, atr_ratio_value=atr, is_panic=panic
    )


class TestConfidenceTrendingBullish:
    def test_strong_bullish_high_confidence(self) -> None:
        snap = _snap(
            close_price=22000.0,
            ema_200=20000.0,
            ema_50=21000.0,
            ema_20=21500.0,
            supertrend_direction=1,
        )
        confidence, score, reasons = _calc.calculate(
            MarketRegime.TRENDING_BULLISH, _dir(), _vol(), snap
        )
        assert confidence >= _cfg.activation.trending
        assert any("ADX" in r for r in reasons)

    def test_hard_gate_caps_at_30(self) -> None:
        confidence, score, reasons = _calc.calculate(
            MarketRegime.TRENDING_BULLISH,
            _dir(adx=18.0, gate=False),
            _vol(),
            _snap(),
        )
        assert confidence <= 30

    def test_elevated_vix_reduces_score(self) -> None:
        snap_no_vix = _snap()
        snap_high_vix = _snap(india_vix=21.0)
        c1, _, _ = _calc.calculate(MarketRegime.TRENDING_BULLISH, _dir(), _vol(), snap_no_vix)
        c2, _, _ = _calc.calculate(MarketRegime.TRENDING_BULLISH, _dir(), _vol(), snap_high_vix)
        assert c2 <= c1


class TestConfidenceTrendingBearish:
    def test_bearish_ema_alignment_adds_score(self) -> None:
        snap = _snap(close_price=18000.0, ema_200=20000.0)
        confidence, _, reasons = _calc.calculate(
            MarketRegime.TRENDING_BEARISH, _dir("BEARISH"), _vol(), snap
        )
        assert any("EMA200" in r for r in reasons)

    def test_supertrend_minus1_confirms_bearish(self) -> None:
        snap = _snap(supertrend_direction=-1)
        confidence, _, reasons = _calc.calculate(
            MarketRegime.TRENDING_BEARISH, _dir("BEARISH"), _vol(), snap
        )
        assert any("supertrend" in r for r in reasons)


class TestConfidenceSideways:
    def test_low_adx_produces_base_score(self) -> None:
        confidence, _, _ = _calc.calculate(
            MarketRegime.SIDEWAYS,
            _dir(adx=18.0, gate=False),
            _vol(vix=16.0),
            _snap(bb_width_percentile=15.0, pcr=1.0),
        )
        assert confidence >= _cfg.activation.sideways

    def test_high_bb_width_no_squeeze_bonus(self) -> None:
        snap_squeeze = _snap(bb_width_percentile=10.0)
        snap_wide = _snap(bb_width_percentile=60.0)
        c_sq, _, _ = _calc.calculate(
            MarketRegime.SIDEWAYS, _dir(adx=15.0, gate=False), _vol(), snap_squeeze
        )
        c_wd, _, _ = _calc.calculate(
            MarketRegime.SIDEWAYS, _dir(adx=15.0, gate=False), _vol(), snap_wide
        )
        assert c_sq >= c_wd


class TestConfidenceHighVolatility:
    def test_panic_vix_gives_high_confidence(self) -> None:
        confidence, _, _ = _calc.calculate(
            MarketRegime.HIGH_VOLATILITY,
            _dir(),
            _vol(level="HIGH", vix=30.0, panic=True),
            _snap(),
        )
        assert confidence >= _cfg.activation.high_volatility

    def test_extreme_iv_adds_to_score(self) -> None:
        snap_no_iv = _snap()
        snap_iv = _snap(iv_percentile=90.0)
        c1, _, _ = _calc.calculate(
            MarketRegime.HIGH_VOLATILITY, _dir(), _vol(level="HIGH", vix=24.0), snap_no_iv
        )
        c2, _, _ = _calc.calculate(
            MarketRegime.HIGH_VOLATILITY, _dir(), _vol(level="HIGH", vix=24.0), snap_iv
        )
        assert c2 > c1


class TestConfidenceLowVolatility:
    def test_very_low_vix_gives_high_confidence(self) -> None:
        confidence, _, _ = _calc.calculate(
            MarketRegime.LOW_VOLATILITY,
            _dir(),
            _vol(level="LOW", vix=12.0, atr=0.6),
            _snap(bb_width_percentile=8.0, iv_percentile=12.0),
        )
        assert confidence >= _cfg.activation.low_volatility

    def test_zero_vix_no_crash(self) -> None:
        confidence, _, _ = _calc.calculate(
            MarketRegime.LOW_VOLATILITY,
            _dir(),
            _vol(level="LOW", vix=0.0),
            _snap(),
        )
        assert 0 <= confidence <= 100


class TestConfidenceOutputBounds:
    def test_confidence_always_0_to_100(self) -> None:
        for regime in MarketRegime:
            c, _, _ = _calc.calculate(regime, _dir(), _vol(), _snap())
            assert 0 <= c <= 100, f"Regime {regime} gave confidence={c}"

    def test_explanation_is_non_empty_list(self) -> None:
        _, _, reasons = _calc.calculate(
            MarketRegime.TRENDING_BULLISH, _dir(), _vol(), _snap()
        )
        assert isinstance(reasons, list)
        assert len(reasons) > 0
