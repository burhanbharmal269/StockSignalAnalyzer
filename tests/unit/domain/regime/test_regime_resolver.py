"""Unit tests for RegimeResolver — all 8 priority rules."""

from __future__ import annotations

from core.domain.enums.market_regime import MarketRegime
from core.domain.regime.regime_resolver import RegimeResolver
from core.domain.regime.trend_layer import DirectionSignal
from core.domain.regime.volatility_layer import VolatilitySignal
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()
_resolver = RegimeResolver(_cfg)


def _dir(
    direction: str = "NEUTRAL",
    adx: float = 20.0,
    spread: float = 3.0,
    gate: bool = False,
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


class TestRule1Panic:
    def test_panic_returns_high_volatility(self) -> None:
        primary, secondary = _resolver.resolve(_dir(), _vol(panic=True))
        assert primary == MarketRegime.HIGH_VOLATILITY
        assert secondary is None

    def test_panic_overrides_trending_gate(self) -> None:
        primary, _ = _resolver.resolve(
            _dir("BULLISH", adx=35.0, spread=20.0, gate=True),
            _vol(level="HIGH", panic=True),
        )
        assert primary == MarketRegime.HIGH_VOLATILITY


class TestRule2HighVolNoTrend:
    def test_high_vol_low_adx_returns_high_volatility(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("NEUTRAL", adx=20.0, gate=False),
            _vol(level="HIGH"),
        )
        assert primary == MarketRegime.HIGH_VOLATILITY
        assert secondary is None

    def test_high_vol_gate_not_open_returns_high_volatility(self) -> None:
        primary, _ = _resolver.resolve(
            _dir("BULLISH", adx=26.0, spread=4.0, gate=False),
            _vol(level="HIGH"),
        )
        assert primary == MarketRegime.HIGH_VOLATILITY


class TestRule3HighVolBullish:
    def test_high_vol_bullish_trending(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("BULLISH", adx=30.0, spread=15.0, gate=True),
            _vol(level="HIGH"),
        )
        assert primary == MarketRegime.TRENDING_BULLISH
        assert secondary == MarketRegime.HIGH_VOLATILITY


class TestRule4HighVolBearish:
    def test_high_vol_bearish_trending(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("BEARISH", adx=30.0, spread=15.0, gate=True),
            _vol(level="HIGH"),
        )
        assert primary == MarketRegime.TRENDING_BEARISH
        assert secondary == MarketRegime.HIGH_VOLATILITY


class TestRule5LowVol:
    def test_low_vol_returns_low_volatility(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir(),
            _vol(level="LOW"),
        )
        assert primary == MarketRegime.LOW_VOLATILITY
        assert secondary is None


class TestRule6NormalBullish:
    def test_normal_vol_bullish_trending(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("BULLISH", adx=30.0, spread=15.0, gate=True),
            _vol(level="NORMAL"),
        )
        assert primary == MarketRegime.TRENDING_BULLISH
        assert secondary is None


class TestRule7NormalBearish:
    def test_normal_vol_bearish_trending(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("BEARISH", adx=30.0, spread=15.0, gate=True),
            _vol(level="NORMAL"),
        )
        assert primary == MarketRegime.TRENDING_BEARISH
        assert secondary is None


class TestRule8Fallthrough:
    def test_fallthrough_returns_sideways(self) -> None:
        primary, secondary = _resolver.resolve(
            _dir("NEUTRAL", adx=18.0, gate=False),
            _vol(level="NORMAL"),
        )
        assert primary == MarketRegime.SIDEWAYS
        assert secondary is None

    def test_normal_vol_gate_closed_returns_sideways(self) -> None:
        primary, _ = _resolver.resolve(
            _dir("BULLISH", adx=22.0, spread=2.0, gate=False),
            _vol(level="NORMAL"),
        )
        assert primary == MarketRegime.SIDEWAYS
