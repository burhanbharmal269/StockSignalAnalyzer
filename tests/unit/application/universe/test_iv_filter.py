"""Unit tests for Stage 6 — IVFilter."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.iv_filter import apply_iv_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import IVConfig


_CFG = IVConfig(min_iv_pct=10.0, max_iv_pct=80.0, min_ivr=20.0, max_ivr=90.0)


def _make(
    token: int = 1001,
    iv_pct: float | None = 30.0,
    iv_rank: float | None = 50.0,
) -> InstrumentData:
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
        iv_pct=iv_pct,
        iv_rank=iv_rank,
        atr_14_pct=1.2,
    )


class TestIVFilter:
    def test_valid_iv_passes(self) -> None:
        inst = _make(iv_pct=30.0, iv_rank=50.0)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_iv_none_passes_through(self) -> None:
        inst = _make(iv_pct=None, iv_rank=None)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_iv_below_min_excluded(self) -> None:
        inst = _make(iv_pct=5.0)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "min_iv_pct" in excl[1001]

    def test_iv_above_max_excluded(self) -> None:
        inst = _make(iv_pct=90.0)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "max_iv_pct" in excl[1001]

    def test_ivr_below_min_excluded(self) -> None:
        inst = _make(iv_pct=30.0, iv_rank=10.0)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "min_ivr" in excl[1001]

    def test_ivr_above_max_excluded(self) -> None:
        inst = _make(iv_pct=30.0, iv_rank=95.0)
        passed, excl = apply_iv_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "max_ivr" in excl[1001]

    def test_iv_present_ivr_none_passes(self) -> None:
        inst = _make(iv_pct=30.0, iv_rank=None)
        passed, _ = apply_iv_filter([inst], _CFG)
        assert len(passed) == 1

    def test_empty_input(self) -> None:
        passed, excl = apply_iv_filter([], _CFG)
        assert passed == []
        assert excl == {}
