"""Unit tests for Stage 7 — ATRFilter."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.atr_filter import apply_atr_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import ATRConfig


_CFG = ATRConfig(min_atr_pct=0.30, max_atr_pct=5.00, weight=0.20)


def _make(token: int = 1001, atr_14_pct: float | None = 1.2) -> InstrumentData:
    return InstrumentData(
        instrument_token=token,
        underlying="NIFTY",
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        sector="Index",
        spot_price=23000.0,
        is_banned=False,
        dte=12,
        avg_traded_value_5d=100.0,
        active_strikes_count=10,
        today_volume=5000.0,
        avg_volume_20d=4000.0,
        atm_oi=1000.0,
        bid=200.0,
        ask=201.0,
        iv_pct=15.0,
        iv_rank=45.0,
        atr_14_pct=atr_14_pct,
    )


class TestATRFilter:
    def test_valid_atr_passes(self) -> None:
        inst = _make(atr_14_pct=1.2)
        passed, excl = apply_atr_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_atr_none_hard_excludes(self) -> None:
        inst = _make(atr_14_pct=None)
        passed, excl = apply_atr_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "atr_data_unavailable" in excl[1001]

    def test_atr_below_min_excluded(self) -> None:
        inst = _make(atr_14_pct=0.1)
        passed, excl = apply_atr_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "min_atr_pct" in excl[1001]

    def test_atr_above_max_excluded(self) -> None:
        inst = _make(atr_14_pct=6.0)
        passed, excl = apply_atr_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "max_atr_pct" in excl[1001]

    def test_boundary_values_pass(self) -> None:
        lo = _make(token=1001, atr_14_pct=0.30)
        hi = _make(token=1002, atr_14_pct=5.00)
        passed, _ = apply_atr_filter([lo, hi], _CFG)
        assert len(passed) == 2

    def test_empty_input(self) -> None:
        passed, excl = apply_atr_filter([], _CFG)
        assert passed == []
        assert excl == {}
