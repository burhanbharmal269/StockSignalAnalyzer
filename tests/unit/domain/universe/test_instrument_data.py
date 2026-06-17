"""Unit tests for InstrumentData value object."""

from __future__ import annotations

from datetime import date

import pytest

from core.domain.universe.instrument_data import InstrumentData


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


class TestMidPrice:
    def test_normal(self) -> None:
        inst = _make(bid=200.0, ask=202.0)
        assert inst.mid_price == 201.0

    def test_zero_bid_ask(self) -> None:
        inst = _make(bid=0.0, ask=0.0)
        assert inst.mid_price == 0.0


class TestSpreadPct:
    def test_normal(self) -> None:
        inst = _make(bid=200.0, ask=202.0)
        expected = (202.0 - 200.0) / 201.0 * 100.0
        assert inst.spread_pct == pytest.approx(expected)

    def test_no_live_quote_returns_none(self) -> None:
        inst = _make(bid=0.0, ask=0.0)
        assert inst.spread_pct is None

    def test_zero_spread(self) -> None:
        inst = _make(bid=200.0, ask=200.0)
        assert inst.spread_pct == pytest.approx(0.0)


class TestVolumeRatio:
    def test_normal(self) -> None:
        inst = _make(today_volume=6000.0, avg_volume_20d=4000.0)
        assert inst.volume_ratio == pytest.approx(1.5)

    def test_no_history(self) -> None:
        inst = _make(today_volume=5000.0, avg_volume_20d=0.0)
        assert inst.volume_ratio == 0.0

    def test_below_average(self) -> None:
        inst = _make(today_volume=2000.0, avg_volume_20d=4000.0)
        assert inst.volume_ratio == pytest.approx(0.5)


class TestFrozen:
    def test_is_immutable(self) -> None:
        inst = _make()
        with pytest.raises((AttributeError, TypeError)):
            inst.underlying = "BANKNIFTY"  # type: ignore[misc]
