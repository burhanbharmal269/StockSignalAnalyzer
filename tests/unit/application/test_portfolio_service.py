"""Unit tests — PortfolioService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.portfolio_service import PortfolioService
from core.domain.entities.portfolio import Portfolio
from core.domain.enums.portfolio_type import PortfolioType


def _make_repo(
    active: Portfolio | None = None,
    by_id: Portfolio | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_active = AsyncMock(return_value=active)
    repo.get_by_id = AsyncMock(return_value=by_id)
    repo.get_active_by_type = AsyncMock(return_value=None)
    repo.list_all = AsyncMock(return_value=[])
    repo.deactivate_all = AsyncMock()
    return repo


def _make_service(repo: MagicMock | None = None) -> PortfolioService:
    return PortfolioService(repository=repo or _make_repo())


def _make_portfolio(is_active: bool = False) -> Portfolio:
    p = Portfolio.create(name="Test", portfolio_type=PortfolioType.DEFAULT)
    if is_active:
        p.activate()
    return p


class TestCreatePortfolio:
    async def test_create_saves(self) -> None:
        repo = _make_repo()
        service = _make_service(repo)
        p = await service.create(name="Main", portfolio_type=PortfolioType.LIVE)
        repo.save.assert_awaited_once()
        assert p.name == "Main"
        assert p.portfolio_type == PortfolioType.LIVE

    async def test_create_with_links(self) -> None:
        repo = _make_repo()
        service = _make_service(repo)
        rid = uuid.uuid4()
        aid = uuid.uuid4()
        p = await service.create(
            name="Linked",
            portfolio_type=PortfolioType.DEFAULT,
            risk_profile_id=rid,
            allocation_id=aid,
        )
        assert p.risk_profile_id == rid
        assert p.allocation_id == aid


class TestActivatePortfolio:
    async def test_activate_deactivates_all_first(self) -> None:
        portfolio = _make_portfolio()
        repo = _make_repo(by_id=portfolio)
        service = _make_service(repo)
        result = await service.activate(portfolio.portfolio_id)
        repo.deactivate_all.assert_awaited_once()
        assert result.is_active is True

    async def test_activate_not_found_raises(self) -> None:
        repo = _make_repo(by_id=None)
        service = _make_service(repo)
        with pytest.raises(ValueError, match="not found"):
            await service.activate(uuid.uuid4())

    async def test_deactivate(self) -> None:
        portfolio = _make_portfolio(is_active=True)
        repo = _make_repo(by_id=portfolio)
        service = _make_service(repo)
        result = await service.deactivate(portfolio.portfolio_id)
        assert result.is_active is False


class TestPortfolioQueries:
    async def test_get_active_none(self) -> None:
        service = _make_service(_make_repo(active=None))
        assert await service.get_active() is None

    async def test_get_active_returns(self) -> None:
        p = _make_portfolio(is_active=True)
        service = _make_service(_make_repo(active=p))
        result = await service.get_active()
        assert result is p

    async def test_assign_risk_profile(self) -> None:
        p = _make_portfolio()
        repo = _make_repo(by_id=p)
        service = _make_service(repo)
        rid = uuid.uuid4()
        result = await service.assign_risk_profile(p.portfolio_id, rid)
        assert result.risk_profile_id == rid

    async def test_assign_allocation(self) -> None:
        p = _make_portfolio()
        repo = _make_repo(by_id=p)
        service = _make_service(repo)
        aid = uuid.uuid4()
        result = await service.assign_allocation(p.portfolio_id, aid)
        assert result.allocation_id == aid
