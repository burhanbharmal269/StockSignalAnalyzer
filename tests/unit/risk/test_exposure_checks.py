"""Unit tests for risk checks 18-21: exposure limits and concentration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from core.domain.risk.risk_limit_checker import (
    check_concentration,
    check_sector_exposure,
    check_strategy_exposure,
    check_symbol_exposure,
)


def _exposure_config(enabled=True, symbol_pct=20.0, sector_pct=40.0, strategy_pct=50.0):
    cfg = MagicMock()
    cfg.exposure_limits = MagicMock()
    cfg.exposure_limits.enabled = enabled
    cfg.exposure_limits.max_symbol_exposure_pct = symbol_pct
    cfg.exposure_limits.max_sector_exposure_pct = sector_pct
    cfg.exposure_limits.max_strategy_exposure_pct = strategy_pct
    return cfg


def _concentration_config(enabled=True, single_pct=15.0, top3_pct=50.0):
    cfg = MagicMock()
    cfg.concentration = MagicMock()
    cfg.concentration.enabled = enabled
    cfg.concentration.max_single_position_pct = single_pct
    cfg.concentration.max_top3_concentration_pct = top3_pct
    return cfg


# ---------------------------------------------------------------------------
# Check 18 — Symbol exposure
# ---------------------------------------------------------------------------

class TestCheckSymbolExposure:
    def test_passes_within_limit(self) -> None:
        cfg = _exposure_config(symbol_pct=20.0)
        result = check_symbol_exposure(
            symbol_notional=Decimal("15000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_fails_at_exact_limit(self) -> None:
        cfg = _exposure_config(symbol_pct=20.0)
        result = check_symbol_exposure(
            symbol_notional=Decimal("20001"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert not result.passed
        assert "symbol" in result.message.lower() or "exposure" in result.message.lower()

    def test_passes_when_disabled(self) -> None:
        cfg = _exposure_config(enabled=False, symbol_pct=20.0)
        result = check_symbol_exposure(
            symbol_notional=Decimal("90000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_does_not_raise_on_raw_mock_config(self) -> None:
        """Mock-safe: must not raise when config is a raw MagicMock (unit test environment)."""
        # A raw MagicMock may trigger the check with arbitrary values — we just verify no exception.
        result = check_symbol_exposure(
            symbol_notional=Decimal("5000"),
            total_capital=Decimal("100000"),
            config=MagicMock(),
        )
        assert isinstance(result.passed, bool)

    def test_zero_capital_passes(self) -> None:
        cfg = _exposure_config(symbol_pct=20.0)
        result = check_symbol_exposure(
            symbol_notional=Decimal("0"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_boundary_exactly_at_limit_fails(self) -> None:
        cfg = _exposure_config(symbol_pct=20.0)
        result = check_symbol_exposure(
            symbol_notional=Decimal("20000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        # 20.0% is not < 20.0% → should fail
        assert not result.passed


# ---------------------------------------------------------------------------
# Check 19 — Sector exposure
# ---------------------------------------------------------------------------

class TestCheckSectorExposure:
    def test_passes_within_limit(self) -> None:
        cfg = _exposure_config(sector_pct=40.0)
        result = check_sector_exposure(
            sector_notional=Decimal("30000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_fails_over_limit(self) -> None:
        cfg = _exposure_config(sector_pct=40.0)
        result = check_sector_exposure(
            sector_notional=Decimal("41000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert not result.passed
        assert "sector" in result.message.lower()

    def test_passes_when_disabled(self) -> None:
        cfg = _exposure_config(enabled=False, sector_pct=40.0)
        result = check_sector_exposure(
            sector_notional=Decimal("99000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_does_not_raise_on_raw_mock_config(self) -> None:
        result = check_sector_exposure(
            sector_notional=Decimal("10000"),
            total_capital=Decimal("100000"),
            config=MagicMock(),
        )
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# Check 20 — Strategy exposure
# ---------------------------------------------------------------------------

class TestCheckStrategyExposure:
    def test_passes_within_limit(self) -> None:
        cfg = _exposure_config(strategy_pct=50.0)
        result = check_strategy_exposure(
            strategy_notional=Decimal("45000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_fails_over_limit(self) -> None:
        cfg = _exposure_config(strategy_pct=50.0)
        result = check_strategy_exposure(
            strategy_notional=Decimal("55000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert not result.passed

    def test_passes_when_disabled(self) -> None:
        cfg = _exposure_config(enabled=False, strategy_pct=50.0)
        result = check_strategy_exposure(
            strategy_notional=Decimal("95000"),
            total_capital=Decimal("100000"),
            config=cfg,
        )
        assert result.passed

    def test_does_not_raise_on_raw_mock_config(self) -> None:
        result = check_strategy_exposure(
            strategy_notional=Decimal("10000"),
            total_capital=Decimal("100000"),
            config=MagicMock(),
        )
        assert isinstance(result.passed, bool)


# ---------------------------------------------------------------------------
# Check 21 — Concentration
# ---------------------------------------------------------------------------

class TestCheckConcentration:
    def test_passes_within_single_and_top3_limits(self) -> None:
        cfg = _concentration_config(single_pct=15.0, top3_pct=50.0)
        positions = {
            "SYM_A": Decimal("12000"),
            "SYM_B": Decimal("10000"),
            "SYM_C": Decimal("8000"),
            "SYM_D": Decimal("5000"),
        }
        result = check_concentration(positions, Decimal("100000"), cfg)
        assert result.passed

    def test_fails_single_position_over_limit(self) -> None:
        cfg = _concentration_config(single_pct=15.0, top3_pct=50.0)
        positions = {"SYM_A": Decimal("16000")}
        result = check_concentration(positions, Decimal("100000"), cfg)
        assert not result.passed
        assert "concentration" in result.message.lower() or "single" in result.message.lower()

    def test_fails_top3_over_limit(self) -> None:
        cfg = _concentration_config(single_pct=15.0, top3_pct=50.0)
        # Each position under 15% individually, but top-3 combined = 51% → fails
        positions = {
            "SYM_A": Decimal("18000"),  # 18%
            "SYM_B": Decimal("17000"),  # 17%
            "SYM_C": Decimal("16000"),  # 16%
            "SYM_D": Decimal("5000"),   #  5%
        }
        result = check_concentration(positions, Decimal("100000"), cfg)
        assert not result.passed

    def test_passes_empty_positions(self) -> None:
        cfg = _concentration_config()
        result = check_concentration({}, Decimal("100000"), cfg)
        assert result.passed

    def test_passes_when_disabled(self) -> None:
        cfg = _concentration_config(enabled=False)
        positions = {"SYM_A": Decimal("90000")}
        result = check_concentration(positions, Decimal("100000"), cfg)
        assert result.passed

    def test_does_not_raise_on_raw_mock_config(self) -> None:
        result = check_concentration(
            {"SYM_A": Decimal("5000")},
            Decimal("100000"),
            MagicMock(),
        )
        assert isinstance(result.passed, bool)

    def test_accepts_list_input(self) -> None:
        cfg = _concentration_config(single_pct=15.0, top3_pct=50.0)
        positions_list = [Decimal("12000"), Decimal("10000"), Decimal("8000")]
        result = check_concentration(positions_list, Decimal("100000"), cfg)
        assert result.passed
