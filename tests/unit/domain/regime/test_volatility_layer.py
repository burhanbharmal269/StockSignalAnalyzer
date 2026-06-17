"""Unit tests for VolatilityLayer."""

from __future__ import annotations

import pytest

from core.domain.regime.volatility_layer import VolatilityLayer, VolatilitySignal
from core.domain.value_objects.feature_snapshot import FeatureSnapshot
from core.infrastructure.config.regime_config import load_regime_config

_cfg = load_regime_config()
_layer = VolatilityLayer(_cfg)


def _snap(**kwargs) -> FeatureSnapshot:
    return FeatureSnapshot(**{"instrument_token": 1, "timeframe": "15m", **kwargs})


class TestVolatilityLayerMissingFields:
    def test_returns_normal_when_vix_missing(self) -> None:
        result = _layer.evaluate(_snap())
        assert result.level == "NORMAL"
        assert result.is_panic is False
        assert result.vix_value == 0.0

    def test_returns_normal_when_only_atr_present(self) -> None:
        result = _layer.evaluate(_snap(atr_ratio=1.2))
        assert result.level == "NORMAL"


class TestVolatilityLayerPanic:
    def test_panic_when_vix_above_28(self) -> None:
        result = _layer.evaluate(_snap(india_vix=30.0))
        assert result.level == "HIGH"
        assert result.is_panic is True

    def test_panic_boundary_exact(self) -> None:
        result = _layer.evaluate(_snap(india_vix=28.1))
        assert result.is_panic is True

    def test_no_panic_at_28_exactly(self) -> None:
        result = _layer.evaluate(_snap(india_vix=28.0))
        assert result.is_panic is False


class TestVolatilityLayerHigh:
    def test_high_when_vix_above_22(self) -> None:
        result = _layer.evaluate(_snap(india_vix=24.0))
        assert result.level == "HIGH"
        assert result.is_panic is False

    def test_high_when_atr_ratio_above_2(self) -> None:
        result = _layer.evaluate(_snap(india_vix=18.0, atr_ratio=2.1))
        assert result.level == "HIGH"
        assert result.is_panic is False

    def test_not_high_when_vix_22_exactly(self) -> None:
        result = _layer.evaluate(_snap(india_vix=22.0, atr_ratio=1.0))
        assert result.level == "NORMAL"


class TestVolatilityLayerLow:
    def test_low_when_vix_below_13(self) -> None:
        result = _layer.evaluate(_snap(india_vix=12.0))
        assert result.level == "LOW"

    def test_low_when_vix_below_14_and_atr_low(self) -> None:
        result = _layer.evaluate(_snap(india_vix=13.5, atr_ratio=0.7))
        assert result.level == "LOW"

    def test_not_low_when_vix_below_14_but_atr_high(self) -> None:
        result = _layer.evaluate(_snap(india_vix=13.5, atr_ratio=1.2))
        assert result.level == "NORMAL"


class TestVolatilityLayerNormal:
    def test_normal_mid_range_vix(self) -> None:
        result = _layer.evaluate(_snap(india_vix=18.0, atr_ratio=1.0))
        assert result.level == "NORMAL"

    def test_returns_frozen_dataclass(self) -> None:
        result = _layer.evaluate(_snap(india_vix=18.0))
        assert isinstance(result, VolatilitySignal)
        with pytest.raises(Exception):  # noqa: B017
            result.level = "X"  # type: ignore[misc]
