"""Unit tests for TrendLayer."""

from __future__ import annotations

import pytest

from core.domain.regime.trend_layer import DirectionSignal, TrendLayer
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()
_layer = TrendLayer(_cfg)


def _snap(**kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": 1, "timeframe": "15m", **kwargs})


class TestTrendLayerMissingFields:
    def test_returns_neutral_when_adx_missing(self) -> None:
        s = _snap(di_plus=30.0, di_minus=10.0)
        result = _layer.evaluate(s)
        assert result.direction == "NEUTRAL"
        assert result.is_gate_open is False

    def test_returns_neutral_when_di_plus_missing(self) -> None:
        s = _snap(adx=30.0, di_minus=10.0)
        result = _layer.evaluate(s)
        assert result.direction == "NEUTRAL"

    def test_returns_neutral_when_all_missing(self) -> None:
        s = _snap()
        result = _layer.evaluate(s)
        assert result.direction == "NEUTRAL"
        assert result.adx_strength == 0.0
        assert result.di_spread == 0.0


class TestTrendLayerGate:
    def test_gate_closed_when_adx_below_strong(self) -> None:
        s = _snap(adx=20.0, di_plus=30.0, di_minus=10.0)
        result = _layer.evaluate(s)
        assert result.is_gate_open is False
        assert result.direction == "NEUTRAL"

    def test_gate_closed_when_di_spread_too_small(self) -> None:
        s = _snap(adx=30.0, di_plus=25.0, di_minus=23.0)  # spread = 2 < 5
        result = _layer.evaluate(s)
        assert result.is_gate_open is False

    def test_gate_open_with_strong_adx_and_spread(self) -> None:
        s = _snap(adx=30.0, di_plus=30.0, di_minus=10.0)  # spread = 20
        result = _layer.evaluate(s)
        assert result.is_gate_open is True


class TestTrendLayerDirection:
    def test_bullish_when_di_plus_gt_di_minus(self) -> None:
        s = _snap(adx=30.0, di_plus=35.0, di_minus=15.0)
        result = _layer.evaluate(s)
        assert result.direction == "BULLISH"

    def test_bearish_when_di_minus_gt_di_plus(self) -> None:
        s = _snap(adx=30.0, di_plus=15.0, di_minus=35.0)
        result = _layer.evaluate(s)
        assert result.direction == "BEARISH"

    def test_bearish_at_threshold_boundary(self) -> None:
        s = _snap(adx=25.0, di_plus=20.0, di_minus=26.0)  # spread = 6 >= 5
        result = _layer.evaluate(s)
        assert result.direction == "BEARISH"

    def test_returns_frozen_dataclass(self) -> None:
        s = _snap(adx=30.0, di_plus=30.0, di_minus=10.0)
        result = _layer.evaluate(s)
        assert isinstance(result, DirectionSignal)
        with pytest.raises(Exception):  # noqa: B017
            result.direction = "X"  # type: ignore[misc]
