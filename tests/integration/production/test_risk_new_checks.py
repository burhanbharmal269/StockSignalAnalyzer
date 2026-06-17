"""Unit tests for new risk limit checks: MonthlyLoss (Check 16) and VolatilityBlock (Check 17)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain.risk.risk_limit_checker import check_monthly_loss, check_volatility_block


def _make_account(monthly_pnl: float = 0.0) -> MagicMock:
    acct = MagicMock()
    acct.monthly_pnl = monthly_pnl
    return acct


def _make_config(
    total_capital: int = 500_000,
    monthly_limit_pct: float = 10.0,
    monthly_limit_abs: int = 50_000,
    vix_threshold: float = 25.0,
    vix_enabled: bool = True,
) -> MagicMock:
    cfg = MagicMock()
    cfg.capital.total_capital = total_capital
    cfg.monthly_loss.limit_pct = monthly_limit_pct
    cfg.monthly_loss.limit_abs = monthly_limit_abs
    cfg.volatility_block.vix_threshold = vix_threshold
    cfg.volatility_block.enabled = vix_enabled
    return cfg


class TestMonthlyLossCheck:
    def test_passes_when_no_monthly_loss(self) -> None:
        result = check_monthly_loss(_make_account(monthly_pnl=0.0), _make_config())
        assert result.passed is True
        assert result.check_name == "MonthlyLoss"

    def test_passes_when_partial_loss(self) -> None:
        result = check_monthly_loss(_make_account(monthly_pnl=-20_000.0), _make_config())
        assert result.passed is True

    def test_fails_when_abs_limit_breached(self) -> None:
        result = check_monthly_loss(_make_account(monthly_pnl=-51_000.0), _make_config())
        assert result.passed is False
        assert "breaches" in result.message.lower()

    def test_fails_when_pct_limit_breached(self) -> None:
        # 500_000 * 10% = 50_000; abs=50_000 → same → breach at -50_001
        result = check_monthly_loss(_make_account(monthly_pnl=-50_001.0), _make_config())
        assert result.passed is False

    def test_uses_lesser_of_pct_and_abs(self) -> None:
        # pct limit = 500_000 * 5% = 25_000; abs limit = 50_000 → effective = 25_000
        cfg = _make_config(monthly_limit_pct=5.0, monthly_limit_abs=50_000)
        result = check_monthly_loss(_make_account(monthly_pnl=-26_000.0), cfg)
        assert result.passed is False


class TestVolatilityBlockCheck:
    def test_passes_when_vix_below_threshold(self) -> None:
        result = check_volatility_block(20.0, _make_config(vix_threshold=25.0))
        assert result.passed is True

    def test_fails_when_vix_at_threshold(self) -> None:
        result = check_volatility_block(25.0, _make_config(vix_threshold=25.0))
        assert result.passed is False  # threshold is exclusive (<, not <=)

    def test_fails_when_vix_above_threshold(self) -> None:
        result = check_volatility_block(30.5, _make_config(vix_threshold=25.0))
        assert result.passed is False
        assert "blocked" in result.message.lower()

    def test_always_passes_when_disabled(self) -> None:
        result = check_volatility_block(99.0, _make_config(vix_threshold=25.0, vix_enabled=False))
        assert result.passed is True
        assert "disabled" in result.message.lower()

    def test_check_name(self) -> None:
        result = check_volatility_block(10.0, _make_config())
        assert result.check_name == "VolatilityBlock"
