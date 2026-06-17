"""Unit tests for Stage 4 — OIRanker."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.oi_ranker import apply_oi_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import OIConfig


_CFG = OIConfig(min_oi_lots=500, atm_oi_band_pct=10.0, weight=0.30)


def _make(token: int = 1001, atm_oi: float = 1000.0) -> InstrumentData:
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
        atm_oi=atm_oi,
        bid=200.0,
        ask=201.0,
        iv_pct=15.0,
        iv_rank=45.0,
        atr_14_pct=1.2,
    )


class TestOIFilter:
    def test_above_min_passes(self) -> None:
        inst = _make(atm_oi=1000.0)
        passed, excl = apply_oi_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_below_min_excluded(self) -> None:
        inst = _make(atm_oi=499.0)
        passed, excl = apply_oi_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "min_oi_lots" in excl[1001]

    def test_at_min_boundary_passes(self) -> None:
        inst = _make(atm_oi=500.0)
        passed, _ = apply_oi_filter([inst], _CFG)
        assert len(passed) == 1

    def test_sorted_descending(self) -> None:
        a = _make(token=1001, atm_oi=600.0)
        b = _make(token=1002, atm_oi=2000.0)
        c = _make(token=1003, atm_oi=1200.0)
        passed, _ = apply_oi_filter([a, b, c], _CFG)
        assert [i.instrument_token for i in passed] == [1002, 1003, 1001]

    def test_empty_input(self) -> None:
        passed, excl = apply_oi_filter([], _CFG)
        assert passed == []
        assert excl == {}
