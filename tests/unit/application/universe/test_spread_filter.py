"""Unit tests for Stage 5 — SpreadFilter."""

from __future__ import annotations

from datetime import date

from core.application.services.universe.spread_filter import apply_spread_filter
from core.domain.universe.instrument_data import InstrumentData
from core.infrastructure.config.universe_config import SpreadConfig


_CFG = SpreadConfig(max_spread_pct=0.50, weight=0.20)


def _make(token: int = 1001, bid: float = 200.0, ask: float = 201.0) -> InstrumentData:
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
        bid=bid,
        ask=ask,
        iv_pct=15.0,
        iv_rank=45.0,
        atr_14_pct=1.2,
    )


class TestSpreadFilter:
    def test_tight_spread_passes(self) -> None:
        # mid = 200.5, spread = 1/200.5*100 ≈ 0.499%
        inst = _make(bid=200.0, ask=201.0)
        passed, excl = apply_spread_filter([inst], _CFG)
        assert len(passed) == 1
        assert not excl

    def test_wide_spread_excluded(self) -> None:
        # mid = 101, spread = 2/101*100 ≈ 1.98%
        inst = _make(bid=100.0, ask=102.0)
        passed, excl = apply_spread_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "spread_pct" in excl[1001]

    def test_no_quote_excluded(self) -> None:
        inst = _make(bid=0.0, ask=0.0)
        passed, excl = apply_spread_filter([inst], _CFG)
        assert not passed
        assert 1001 in excl
        assert "no_live_quote" in excl[1001]

    def test_zero_spread_passes(self) -> None:
        inst = _make(bid=200.0, ask=200.0)
        passed, _ = apply_spread_filter([inst], _CFG)
        assert len(passed) == 1

    def test_empty_input(self) -> None:
        passed, excl = apply_spread_filter([], _CFG)
        assert passed == []
        assert excl == {}
