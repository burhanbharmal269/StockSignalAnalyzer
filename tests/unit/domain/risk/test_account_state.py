"""Unit tests for AccountState domain value object."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.domain.exceptions.risk import RiskInvariantError
from core.domain.risk.account_state import AccountState

_NOW = datetime.now(UTC)


def _make(**overrides: object) -> AccountState:
    defaults: dict[str, object] = {
        "account_capital": Decimal("500000"),
        "session_capital": Decimal("500000"),
        "available_margin": Decimal("400000"),
        "used_margin": Decimal("100000"),
        "margin_utilization_pct": 20.0,
        "daily_pnl": Decimal("0"),
        "daily_loss_consumed_pct": 0.0,
        "weekly_pnl": Decimal("0"),
        "weekly_loss_consumed_pct": 0.0,
        "drawdown_from_hwm_pct": 0.0,
        "open_positions_count": 0,
        "position_size_multiplier": 1.0,
        "trading_mode": "LIVE",
        "captured_at": _NOW,
    }
    defaults.update(overrides)
    return AccountState(**defaults)  # type: ignore[arg-type]


class TestAccountStateConstruction:
    def test_valid_construction(self) -> None:
        state = _make()
        assert state.account_capital == Decimal("500000")
        assert state.trading_mode == "LIVE"

    def test_is_frozen(self) -> None:
        state = _make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            state.trading_mode = "PAPER"  # type: ignore[misc]

    def test_negative_account_capital_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="account_capital"):
            _make(account_capital=Decimal("-1"))

    def test_negative_session_capital_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="session_capital"):
            _make(session_capital=Decimal("-0.01"))

    def test_negative_available_margin_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="available_margin"):
            _make(available_margin=Decimal("-100"))

    def test_negative_used_margin_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="used_margin"):
            _make(used_margin=Decimal("-1"))

    def test_negative_margin_utilization_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="margin_utilization_pct"):
            _make(margin_utilization_pct=-0.1)

    def test_negative_daily_loss_consumed_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="daily_loss_consumed_pct"):
            _make(daily_loss_consumed_pct=-1.0)

    def test_negative_weekly_loss_consumed_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="weekly_loss_consumed_pct"):
            _make(weekly_loss_consumed_pct=-0.5)

    def test_negative_drawdown_pct_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="drawdown_from_hwm_pct"):
            _make(drawdown_from_hwm_pct=-1.0)

    def test_negative_open_positions_count_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="open_positions_count"):
            _make(open_positions_count=-1)

    def test_invalid_position_size_multiplier_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="position_size_multiplier"):
            _make(position_size_multiplier=0.75)

    def test_valid_multipliers(self) -> None:
        for multiplier in (0.0, 0.5, 1.0):
            state = _make(position_size_multiplier=multiplier)
            assert state.position_size_multiplier == multiplier

    def test_invalid_trading_mode_raises(self) -> None:
        with pytest.raises(RiskInvariantError, match="trading_mode"):
            _make(trading_mode="UNKNOWN")

    def test_valid_trading_modes(self) -> None:
        for mode in ("LIVE", "PAPER", "BLOCKED"):
            state = _make(trading_mode=mode)
            assert state.trading_mode == mode

    def test_zero_capital_is_valid(self) -> None:
        state = _make(account_capital=Decimal("0"), session_capital=Decimal("0"))
        assert state.account_capital == Decimal("0")
