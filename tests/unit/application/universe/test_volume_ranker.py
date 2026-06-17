"""Unit tests for Stage 3 — VolumeRanker."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.volume_ranker import apply_volume_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import VolumeConfig


_CFG = VolumeConfig(min_volume_ratio=0.5, weight=0.30)


def _make(token: int = 1001, today_vol: float = 5000.0, avg_vol: float = 4000.0) -> InstrumentData:
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
        today_volume=today_vol,
        avg_volume_20d=avg_vol,
        atm_oi=1000.0,
        bid=200.0,
        ask=201.0,
        iv_pct=15.0,
        iv_rank=45.0,
        atr_14_pct=1.2,
    )


class TestVolumeFilter:
    def test_above_threshold_passes(self) -> None:
        inst = _make(today_vol=5000.0, avg_vol=4000.0)  # ratio = 1.25
        passed, excl = apply_volume_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_below_threshold_excluded(self) -> None:
        inst = _make(today_vol=1000.0, avg_vol=4000.0)  # ratio = 0.25
        passed, excl = apply_volume_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "volume_ratio" in excl[1001]

    def test_no_history_excluded(self) -> None:
        inst = _make(today_vol=5000.0, avg_vol=0.0)  # ratio = 0.0
        passed, excl = apply_volume_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl

    def test_sorted_descending(self) -> None:
        low = _make(token=1001, today_vol=3000.0, avg_vol=4000.0)   # ratio = 0.75
        high = _make(token=1002, today_vol=8000.0, avg_vol=4000.0)  # ratio = 2.0
        mid = _make(token=1003, today_vol=5000.0, avg_vol=4000.0)   # ratio = 1.25
        passed, _ = apply_volume_filter([low, high, mid], _CFG)
        assert [i.instrument_token for i in passed] == [1002, 1003, 1001]

    def test_empty_input(self) -> None:
        passed, excl = apply_volume_filter([], _CFG)
        assert passed == []
        assert excl == {}
