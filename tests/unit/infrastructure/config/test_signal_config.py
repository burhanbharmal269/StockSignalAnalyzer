"""Unit tests for SignalConfig (Pydantic model + loader)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.infrastructure.config.signal_config import (
    SignalConfig,
    SignalGateConfig,
    load_signal_config,
)


class TestSignalGateConfig:
    def test_defaults(self) -> None:
        cfg = SignalGateConfig()
        assert cfg.min_score == 70
        assert cfg.min_confidence == 65

    def test_invalid_score_out_of_range(self) -> None:
        with pytest.raises(Exception):
            SignalGateConfig(min_score=101)

    def test_invalid_confidence_negative(self) -> None:
        with pytest.raises(Exception):
            SignalGateConfig(min_confidence=-1)


class TestSignalConfig:
    def test_defaults(self) -> None:
        cfg = SignalConfig()
        assert cfg.ttl_minutes == 15
        assert cfg.dedup_ttl_minutes == 30
        assert cfg.market_close_time == "15:15:00"

    def test_ttl_seconds_property(self) -> None:
        cfg = SignalConfig(ttl_minutes=15)
        assert cfg.ttl_seconds == 900

    def test_dedup_ttl_seconds_property(self) -> None:
        cfg = SignalConfig(dedup_ttl_minutes=30)
        assert cfg.dedup_ttl_seconds == 1800

    def test_dedup_shorter_than_ttl_raises(self) -> None:
        with pytest.raises(Exception):
            SignalConfig(ttl_minutes=30, dedup_ttl_minutes=15)

    def test_dedup_key_format(self) -> None:
        cfg = SignalConfig()
        key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "abc123")
        assert key == "signal:dedup:1234:LONG:DIRECTIONAL:TRENDING_BULLISH:abc123"

    def test_dedup_key_distinguishes_strategy(self) -> None:
        cfg = SignalConfig()
        trend_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "w")
        mr_key = cfg.dedup_key(1234, "LONG", "MEAN_REVERSION", "TRENDING_BULLISH", "w")
        assert trend_key != mr_key

    def test_dedup_key_distinguishes_regime(self) -> None:
        cfg = SignalConfig()
        bull_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "w")
        bear_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BEARISH", "w")
        assert bull_key != bear_key

    def test_active_key_format(self) -> None:
        cfg = SignalConfig()
        key = cfg.active_key(5678)
        assert key == "signal:active:5678"

    def test_zero_ttl_raises(self) -> None:
        with pytest.raises(Exception):
            SignalConfig(ttl_minutes=0)


class TestLoadSignalConfig:
    def test_load_from_file(self) -> None:
        path = Path(__file__).parents[4] / "config" / "signal.yaml"
        cfg = load_signal_config(path)
        assert cfg.ttl_minutes == 15
        assert cfg.gate.min_score == 70
        assert cfg.gate.min_confidence == 65
        assert cfg.dedup_ttl_minutes == 30
