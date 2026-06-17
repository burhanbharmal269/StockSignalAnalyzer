"""Unit tests for Stage 2 — LiquidityFilter."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.liquidity_filter import apply_liquidity_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import LiquidityConfig


_CFG = LiquidityConfig(min_liquidity_crores=50.0, min_active_strikes=5)


def _make(**overrides: object) -> InstrumentData:
    defaults: dict[str, object] = {
        "instrument_token": 1001,
        "underlying": "NIFTY",
        "instrument_class": "OPTION",
        "expiry_date": date(2026, 6, 26),
        "sector": "Index",
        "spot_price": 23000.0,
        "is_banned": False,
        "dte": 12,
        "avg_traded_value_5d": 100.0,
        "active_strikes_count": 10,
        "today_volume": 5000.0,
        "avg_volume_20d": 4000.0,
        "atm_oi": 1000.0,
        "bid": 200.0,
        "ask": 201.0,
        "iv_pct": 15.0,
        "iv_rank": 45.0,
        "atr_14_pct": 1.2,
    }
    defaults.update(overrides)
    return InstrumentData(**defaults)  # type: ignore[arg-type]


class TestLiquidityFilter:
    def test_passes_above_both_thresholds(self) -> None:
        inst = _make(avg_traded_value_5d=100.0, active_strikes_count=10)
        passed, excl = apply_liquidity_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_low_atv_excluded(self) -> None:
        inst = _make(avg_traded_value_5d=49.9)
        passed, excl = apply_liquidity_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "avg_traded_value_5d" in excl[1001]

    def test_few_strikes_excluded(self) -> None:
        inst = _make(active_strikes_count=4)
        passed, excl = apply_liquidity_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "active_strikes_count" in excl[1001]

    def test_both_thresholds_at_exact_boundary(self) -> None:
        inst = _make(avg_traded_value_5d=50.0, active_strikes_count=5)
        passed, _ = apply_liquidity_filter([inst], _CFG)
        assert len(passed) == 1

    def test_empty_input(self) -> None:
        passed, excl = apply_liquidity_filter([], _CFG)
        assert passed == []
        assert excl == {}
