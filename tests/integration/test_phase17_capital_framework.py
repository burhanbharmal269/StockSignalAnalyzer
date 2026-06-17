"""Integration tests — Phase 17 Capital Allocation Framework.

Uses in-memory SQLite (via async_sessionmaker) to test the full
repository → service → domain round-trip without PostgreSQL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.application.services.capital_allocation_service import CapitalAllocationService
from core.application.services.portfolio_service import PortfolioService
from core.application.services.risk_profile_service import RiskProfileService
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.portfolio_type import PortfolioType
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope
from core.infrastructure.database.models.base import Base
from core.infrastructure.database.models.capital_framework_models import (  # noqa: F401
    AllocationHistoryOrm,
    CapitalAllocationOrm,
    PortfolioOrm,
    RiskProfileOrm,
)
from core.infrastructure.database.repositories.capital_allocation_repository import (
    SqlAlchemyCapitalAllocationRepository,
)
from core.infrastructure.database.repositories.portfolio_repository import (
    SqlAlchemyPortfolioRepository,
)
from core.infrastructure.database.repositories.risk_profile_repository import (
    SqlAlchemyRiskProfileRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Only create Phase 17 tables; other models have PostgreSQL-specific types
    # (ARRAY, JSONB) that SQLite can't handle.
    _phase17_table_names = {
        "risk_profiles",
        "capital_allocations",
        "portfolios",
        "allocation_history",
    }
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    t
                    for t in Base.metadata.sorted_tables
                    if t.name in _phase17_table_names
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory


@pytest_asyncio.fixture
async def risk_profile_service(session_factory: async_sessionmaker) -> RiskProfileService:
    repo = SqlAlchemyRiskProfileRepository(session_factory=session_factory)
    return RiskProfileService(repository=repo)


@pytest_asyncio.fixture
async def capital_service(session_factory: async_sessionmaker) -> CapitalAllocationService:
    repo = SqlAlchemyCapitalAllocationRepository(session_factory=session_factory)
    return CapitalAllocationService(repository=repo)


@pytest_asyncio.fixture
async def portfolio_service(session_factory: async_sessionmaker) -> PortfolioService:
    repo = SqlAlchemyPortfolioRepository(session_factory=session_factory)
    return PortfolioService(repository=repo)


# ---------------------------------------------------------------------------
# RiskProfile integration tests
# ---------------------------------------------------------------------------


class TestRiskProfileIntegration:
    async def test_create_and_retrieve(self, risk_profile_service: RiskProfileService) -> None:
        profile = await risk_profile_service.create(
            name="My Profile",
            profile_type=RiskProfileType.MODERATE,
            universe_scope=UniverseScope.ALL_FNO,
            risk_per_trade_pct=Decimal("2.0"),
            max_open_positions=5,
            daily_loss_pct=Decimal("3.0"),
            weekly_loss_pct=Decimal("8.0"),
            drawdown_pct=Decimal("12.0"),
            max_position_size_pct=Decimal("20.0"),
        )
        retrieved = await risk_profile_service.get_by_id(profile.profile_id)
        assert retrieved is not None
        assert retrieved.name == "My Profile"
        assert retrieved.risk_per_trade_pct == Decimal("2.0")

    async def test_get_active_none_initially(self, risk_profile_service: RiskProfileService) -> None:
        active = await risk_profile_service.get_active()
        assert active is None

    async def test_activate_makes_one_active(self, risk_profile_service: RiskProfileService) -> None:
        p1 = await risk_profile_service.create_from_preset(RiskProfileType.CONSERVATIVE)
        p2 = await risk_profile_service.create_from_preset(RiskProfileType.MODERATE)

        await risk_profile_service.activate(p1.profile_id)
        active = await risk_profile_service.get_active()
        assert active is not None
        assert active.profile_id == p1.profile_id

        # Activating p2 deactivates p1
        await risk_profile_service.activate(p2.profile_id)
        active = await risk_profile_service.get_active()
        assert active.profile_id == p2.profile_id

        p1_reloaded = await risk_profile_service.get_by_id(p1.profile_id)
        assert p1_reloaded is not None
        assert p1_reloaded.is_active is False

    async def test_list_all(self, risk_profile_service: RiskProfileService) -> None:
        await risk_profile_service.create_from_preset(RiskProfileType.CONSERVATIVE)
        await risk_profile_service.create_from_preset(RiskProfileType.MODERATE)
        profiles = await risk_profile_service.list_all()
        assert len(profiles) == 2

    async def test_update_profile(self, risk_profile_service: RiskProfileService) -> None:
        p = await risk_profile_service.create_from_preset(RiskProfileType.MODERATE)
        updated = await risk_profile_service.update(p.profile_id, max_open_positions=8)
        assert updated.max_open_positions == 8
        reloaded = await risk_profile_service.get_by_id(p.profile_id)
        assert reloaded is not None
        assert reloaded.max_open_positions == 8

    async def test_deactivate(self, risk_profile_service: RiskProfileService) -> None:
        p = await risk_profile_service.create_from_preset(RiskProfileType.MODERATE)
        await risk_profile_service.activate(p.profile_id)
        await risk_profile_service.deactivate(p.profile_id)
        active = await risk_profile_service.get_active()
        assert active is None


# ---------------------------------------------------------------------------
# CapitalAllocation integration tests
# ---------------------------------------------------------------------------


class TestCapitalAllocationIntegration:
    async def test_create_and_retrieve(self, capital_service: CapitalAllocationService) -> None:
        a = await capital_service.create(
            name="Global Default",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("1000000"),
        )
        retrieved = await capital_service.get_by_id(a.allocation_id)
        assert retrieved is not None
        assert retrieved.allocated_capital == Decimal("1000000")
        assert retrieved.capital_source_mode == CapitalSourceMode.HYBRID

    async def test_activate_one_at_a_time(self, capital_service: CapitalAllocationService) -> None:
        a1 = await capital_service.create(
            name="A1",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("500000"),
        )
        a2 = await capital_service.create(
            name="A2",
            allocation_type=AllocationType.PAPER,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("100000"),
        )
        await capital_service.activate(a1.allocation_id)
        await capital_service.activate(a2.allocation_id)

        active = await capital_service.get_active()
        assert active is not None
        assert active.allocation_id == a2.allocation_id

        a1_reloaded = await capital_service.get_by_id(a1.allocation_id)
        assert a1_reloaded is not None
        assert a1_reloaded.is_active is False

    async def test_update_capital_persists(self, capital_service: CapitalAllocationService) -> None:
        a = await capital_service.create(
            name="Test",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("1000000"),
        )
        await capital_service.update_capital(
            allocation_id=a.allocation_id,
            new_capital=Decimal("2000000"),
            new_margin=Decimal("800000"),
        )
        reloaded = await capital_service.get_by_id(a.allocation_id)
        assert reloaded is not None
        assert reloaded.allocated_capital == Decimal("2000000")
        assert reloaded.allocated_margin == Decimal("800000")

    async def test_update_mode_persists(self, capital_service: CapitalAllocationService) -> None:
        a = await capital_service.create(
            name="ModeTest",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("500000"),
        )
        await capital_service.update_mode(a.allocation_id, CapitalSourceMode.ACCOUNT)
        reloaded = await capital_service.get_by_id(a.allocation_id)
        assert reloaded is not None
        assert reloaded.capital_source_mode == CapitalSourceMode.ACCOUNT

    async def test_history_is_appended_on_create_and_update(
        self, capital_service: CapitalAllocationService, session_factory: async_sessionmaker
    ) -> None:
        a = await capital_service.create(
            name="HistTest",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("1000000"),
        )
        await capital_service.update_capital(a.allocation_id, Decimal("1500000"))
        await capital_service.activate(a.allocation_id)

        # Verify history rows
        from sqlalchemy import select
        from core.infrastructure.database.models.capital_framework_models import AllocationHistoryOrm

        async with session_factory() as session:
            result = await session.execute(
                select(AllocationHistoryOrm).where(AllocationHistoryOrm.allocation_id == a.allocation_id)
            )
            rows = result.scalars().all()
        # CREATED + CAPITAL_UPDATED + ACTIVATED = 3 rows
        assert len(rows) == 3
        change_types = {r.change_type for r in rows}
        assert "CREATED" in change_types
        assert "CAPITAL_UPDATED" in change_types
        assert "ACTIVATED" in change_types


# ---------------------------------------------------------------------------
# Portfolio integration tests
# ---------------------------------------------------------------------------


class TestPortfolioIntegration:
    async def test_create_and_retrieve(self, portfolio_service: PortfolioService) -> None:
        p = await portfolio_service.create(
            name="Main Portfolio",
            portfolio_type=PortfolioType.DEFAULT,
        )
        retrieved = await portfolio_service.get_by_id(p.portfolio_id)
        assert retrieved is not None
        assert retrieved.name == "Main Portfolio"

    async def test_activate_one_at_a_time(self, portfolio_service: PortfolioService) -> None:
        p1 = await portfolio_service.create(name="P1", portfolio_type=PortfolioType.DEFAULT)
        p2 = await portfolio_service.create(name="P2", portfolio_type=PortfolioType.LIVE)

        await portfolio_service.activate(p1.portfolio_id)
        await portfolio_service.activate(p2.portfolio_id)

        active = await portfolio_service.get_active()
        assert active is not None
        assert active.portfolio_id == p2.portfolio_id

    async def test_assign_risk_profile(self, portfolio_service: PortfolioService) -> None:
        p = await portfolio_service.create(name="P", portfolio_type=PortfolioType.DEFAULT)
        rid = uuid.uuid4()
        await portfolio_service.assign_risk_profile(p.portfolio_id, rid)
        reloaded = await portfolio_service.get_by_id(p.portfolio_id)
        assert reloaded is not None
        assert reloaded.risk_profile_id == rid

    async def test_list_all_returns_all(self, portfolio_service: PortfolioService) -> None:
        await portfolio_service.create(name="P1", portfolio_type=PortfolioType.DEFAULT)
        await portfolio_service.create(name="P2", portfolio_type=PortfolioType.PAPER)
        portfolios = await portfolio_service.list_all()
        assert len(portfolios) == 2
