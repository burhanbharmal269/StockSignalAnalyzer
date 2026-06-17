"""Unit tests — EffectiveAccountStateService.

Tests all three CapitalSourceMode resolution paths:
  ACCOUNT    : uses broker capital/margin directly
  CONFIGURED : uses configured capital/margin
  HYBRID     : uses configured capital for sizing, broker margin for exposure
               (falls back to broker capital when configured_capital is zero)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.effective_account_state_service import EffectiveAccountStateService
from core.domain.entities.capital_allocation import CapitalAllocation
from core.domain.entities.portfolio import Portfolio
from core.domain.entities.risk_profile import RiskProfile
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.portfolio_type import PortfolioType
from core.domain.enums.universe_scope import UniverseScope
from core.domain.risk.account_state import AccountState


def _make_account_state(capital: Decimal = Decimal("1000000"), margin: Decimal = Decimal("400000")) -> AccountState:
    return AccountState(
        account_capital=capital,
        session_capital=capital,
        available_margin=margin,
        used_margin=Decimal("100000"),
        margin_utilization_pct=20.0,
        daily_pnl=Decimal("0"),
        daily_loss_consumed_pct=0.0,
        weekly_pnl=Decimal("0"),
        weekly_loss_consumed_pct=0.0,
        drawdown_from_hwm_pct=0.0,
        open_positions_count=0,
        position_size_multiplier=1.0,
        trading_mode="LIVE",
        captured_at=datetime.now(UTC),
    )


def _make_allocation(
    capital: Decimal = Decimal("500000"),
    margin: Decimal | None = None,
    mode: CapitalSourceMode = CapitalSourceMode.HYBRID,
) -> CapitalAllocation:
    a = CapitalAllocation.create(
        name="Test",
        allocation_type=AllocationType.GLOBAL,
        universe_scope=UniverseScope.ALL_FNO,
        allocated_capital=capital,
        capital_source_mode=mode,
        allocated_margin=margin,
    )
    a.activate()
    return a


def _make_profile() -> RiskProfile:
    p = RiskProfile.moderate()
    p.activate()
    return p


def _make_portfolio() -> Portfolio:
    p = Portfolio.create(name="Test", portfolio_type=PortfolioType.DEFAULT)
    p.activate()
    return p


def _make_service(
    account_state: AccountState | None = None,
    risk_profile: RiskProfile | None = None,
    allocation: CapitalAllocation | None = None,
    portfolio: Portfolio | None = None,
) -> EffectiveAccountStateService:
    account_repo = MagicMock()
    account_repo.get_current = AsyncMock(return_value=account_state or _make_account_state())

    profile_repo = MagicMock()
    profile_repo.get_active = AsyncMock(return_value=risk_profile)

    allocation_repo = MagicMock()
    allocation_repo.get_active = AsyncMock(return_value=allocation)

    portfolio_repo = MagicMock()
    portfolio_repo.get_active = AsyncMock(return_value=portfolio)

    return EffectiveAccountStateService(
        account_state_repo=account_repo,
        risk_profile_repo=profile_repo,
        capital_allocation_repo=allocation_repo,
        portfolio_repo=portfolio_repo,
    )


class TestHybridMode:
    async def test_configured_capital_used_when_set(self) -> None:
        allocation = _make_allocation(capital=Decimal("500000"), mode=CapitalSourceMode.HYBRID)
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=state, allocation=allocation)
        eas = await service.resolve()

        assert eas.capital_source_mode == CapitalSourceMode.HYBRID
        assert eas.effective_capital == Decimal("500000")  # configured wins
        assert eas.effective_margin == Decimal("400000")   # always broker margin in HYBRID

    async def test_falls_back_to_broker_capital_when_configured_zero(self) -> None:
        allocation = _make_allocation(capital=Decimal("0"), mode=CapitalSourceMode.HYBRID)
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=state, allocation=allocation)
        eas = await service.resolve()

        assert eas.effective_capital == Decimal("1000000")  # falls back to broker

    async def test_no_allocation_defaults_to_hybrid_with_broker_capital(self) -> None:
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("300000"))
        service = _make_service(account_state=state, allocation=None)
        eas = await service.resolve()

        assert eas.capital_source_mode == CapitalSourceMode.HYBRID
        assert eas.effective_capital == Decimal("1000000")  # broker fallback


class TestAccountMode:
    async def test_uses_broker_capital_and_margin(self) -> None:
        allocation = _make_allocation(
            capital=Decimal("500000"),
            margin=Decimal("200000"),
            mode=CapitalSourceMode.ACCOUNT,
        )
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=state, allocation=allocation)
        eas = await service.resolve()

        assert eas.capital_source_mode == CapitalSourceMode.ACCOUNT
        assert eas.effective_capital == Decimal("1000000")  # broker
        assert eas.effective_margin == Decimal("400000")    # broker


class TestConfiguredMode:
    async def test_uses_configured_capital_and_margin(self) -> None:
        allocation = _make_allocation(
            capital=Decimal("600000"),
            margin=Decimal("300000"),
            mode=CapitalSourceMode.CONFIGURED,
        )
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=state, allocation=allocation)
        eas = await service.resolve()

        assert eas.capital_source_mode == CapitalSourceMode.CONFIGURED
        assert eas.effective_capital == Decimal("600000")  # configured
        assert eas.effective_margin == Decimal("300000")   # configured

    async def test_falls_back_to_broker_margin_when_configured_margin_none(self) -> None:
        allocation = _make_allocation(
            capital=Decimal("600000"),
            margin=None,   # no configured margin
            mode=CapitalSourceMode.CONFIGURED,
        )
        state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=state, allocation=allocation)
        eas = await service.resolve()

        assert eas.effective_margin == Decimal("400000")  # falls back to broker


class TestRiskLimits:
    async def test_risk_limits_derived_from_profile(self) -> None:
        profile = _make_profile()  # MODERATE: 3% daily, 8% weekly, 12% drawdown, 2% per trade
        allocation = _make_allocation(capital=Decimal("1000000"), mode=CapitalSourceMode.HYBRID)
        service = _make_service(allocation=allocation, risk_profile=profile)
        eas = await service.resolve()

        assert eas.effective_daily_loss_limit == Decimal("30000.00")  # 3% of 1M
        assert eas.effective_weekly_loss_limit == Decimal("80000.00")  # 8% of 1M
        assert eas.effective_max_open_positions == 5
        assert eas.effective_risk_per_trade == Decimal("20000.00")  # 2% of 1M

    async def test_safe_defaults_when_no_profile(self) -> None:
        allocation = _make_allocation(capital=Decimal("1000000"), mode=CapitalSourceMode.HYBRID)
        service = _make_service(allocation=allocation, risk_profile=None)
        eas = await service.resolve()

        # Conservative safe defaults: 2% daily, 5% weekly, 1% per trade
        assert eas.effective_daily_loss_limit == Decimal("20000.00")
        assert eas.effective_risk_per_trade == Decimal("10000.00")
        assert eas.effective_max_open_positions == 5


class TestAuditIds:
    async def test_audit_ids_populated(self) -> None:
        profile = _make_profile()
        allocation = _make_allocation()
        portfolio = _make_portfolio()
        service = _make_service(risk_profile=profile, allocation=allocation, portfolio=portfolio)
        eas = await service.resolve()

        assert eas.risk_profile_id == profile.profile_id
        assert eas.allocation_id == allocation.allocation_id
        assert eas.portfolio_id == portfolio.portfolio_id

    async def test_audit_ids_none_when_no_framework(self) -> None:
        service = _make_service()
        eas = await service.resolve()

        assert eas.risk_profile_id is None
        assert eas.allocation_id is None
        assert eas.portfolio_id is None


class TestToAccountState:
    async def test_to_account_state_replaces_session_capital(self) -> None:
        allocation = _make_allocation(capital=Decimal("750000"), mode=CapitalSourceMode.HYBRID)
        broker_state = _make_account_state(capital=Decimal("1000000"), margin=Decimal("400000"))
        service = _make_service(account_state=broker_state, allocation=allocation)

        eas = await service.resolve()
        replaced = await service.to_account_state(eas)

        assert replaced.session_capital == Decimal("750000")  # from allocation
        assert replaced.available_margin == Decimal("400000")  # broker margin in HYBRID
