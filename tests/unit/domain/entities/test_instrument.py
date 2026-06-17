"""Unit tests for Instrument entity."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.value_objects.symbol import Symbol


def _make_instrument(**kwargs: object) -> Instrument:
    defaults: dict[str, object] = {
        "token": 256265,
        "symbol": Symbol("NIFTY"),
        "name": "NIFTY 50",
        "asset_type": AssetType.FNO,
        "exchange": "NSE",
        "lot_size": 50,
        "tick_size": Decimal("0.05"),
    }
    defaults.update(kwargs)
    return Instrument.create(**defaults)  # type: ignore[arg-type]


class TestInstrumentFactory:
    def test_create_assigns_id(self) -> None:
        inst = _make_instrument()
        assert inst.instrument_id is not None

    def test_is_active_by_default(self) -> None:
        assert _make_instrument().is_active is True

    def test_zero_lot_size_raises(self) -> None:
        with pytest.raises(ValueError):
            _make_instrument(lot_size=0)

    def test_negative_lot_size_raises(self) -> None:
        with pytest.raises(ValueError):
            _make_instrument(lot_size=-10)


class TestInstrumentProperties:
    def test_is_fno_true(self) -> None:
        assert _make_instrument(asset_type=AssetType.FNO).is_fno is True

    def test_is_fno_false_for_equity(self) -> None:
        assert _make_instrument(asset_type=AssetType.EQUITY).is_fno is False

    def test_is_expired_false_future_expiry(self) -> None:
        inst = _make_instrument(expiry=date(2099, 12, 31))
        assert inst.is_expired is False

    def test_is_expired_true_past_expiry(self) -> None:
        inst = _make_instrument(expiry=date(2020, 1, 1))
        assert inst.is_expired is True

    def test_is_expired_false_no_expiry(self) -> None:
        inst = _make_instrument(expiry=None)
        assert inst.is_expired is False

    def test_deactivate(self) -> None:
        inst = _make_instrument()
        inst.deactivate()
        assert inst.is_active is False

    def test_strike_set_correctly(self) -> None:
        inst = _make_instrument(strike=Decimal("19500"))
        assert inst.strike is not None
        assert str(inst.strike) == "19500"
