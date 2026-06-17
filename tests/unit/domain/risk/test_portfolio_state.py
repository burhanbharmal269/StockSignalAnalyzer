"""Unit tests for PortfolioState domain value object."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.portfolio_state import PortfolioState

_NOW = datetime.now(UTC)


def _make(**overrides: object) -> PortfolioState:
    defaults: dict[str, object] = {
        "open_positions_count": 0,
        "positions_per_underlying": {},
        "capital_per_underlying_pct": {},
        "net_delta": 0.0,
        "net_vega": 0.0,
        "net_theta_daily": 0.0,
        "orders_last_minute": 0,
        "orders_today": 0,
        "captured_at": _NOW,
    }
    defaults.update(overrides)
    return PortfolioState(**defaults)  # type: ignore[arg-type]


class TestPortfolioStateConstruction:
    def test_valid_empty_portfolio(self) -> None:
        state = _make()
        assert state.open_positions_count == 0
        assert state.positions_per_underlying == {}

    def test_valid_with_positions(self) -> None:
        state = _make(
            open_positions_count=2,
            positions_per_underlying={"NIFTY": 2},
            capital_per_underlying_pct={"NIFTY": 15.0},
        )
        assert state.open_positions_count == 2
        assert state.positions_per_underlying["NIFTY"] == 2

    def test_is_frozen(self) -> None:
        state = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.open_positions_count = 5  # type: ignore[misc]

    def test_negative_open_positions_count_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="open_positions_count"):
            _make(open_positions_count=-1)

    def test_negative_orders_last_minute_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="orders_last_minute"):
            _make(orders_last_minute=-1)

    def test_negative_positions_per_underlying_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="positions_per_underlying"):
            _make(positions_per_underlying={"NIFTY": -1})

    def test_negative_capital_per_underlying_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="capital_per_underlying_pct"):
            _make(capital_per_underlying_pct={"NIFTY": -0.1})

    def test_net_delta_can_be_negative(self) -> None:
        state = _make(net_delta=-500.0)
        assert state.net_delta == -500.0

    def test_net_theta_can_be_negative(self) -> None:
        state = _make(net_theta_daily=-200.0)
        assert state.net_theta_daily == -200.0

    def test_orders_today_zero_valid(self) -> None:
        state = _make(orders_today=0)
        assert state.orders_today == 0

    def test_orders_today_positive_valid(self) -> None:
        state = _make(orders_today=49)
        assert state.orders_today == 49

    def test_negative_orders_today_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="orders_today"):
            _make(orders_today=-1)
