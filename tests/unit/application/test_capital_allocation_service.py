"""Unit tests — CapitalAllocationService."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.capital_allocation_service import CapitalAllocationService
from core.domain.entities.capital_allocation import CapitalAllocation
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.universe_scope import UniverseScope


def _make_repo(
    active: CapitalAllocation | None = None,
    by_id: CapitalAllocation | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_active = AsyncMock(return_value=active)
    repo.get_by_id = AsyncMock(return_value=by_id)
    repo.list_all = AsyncMock(return_value=[])
    repo.deactivate_all = AsyncMock()
    repo.append_history = AsyncMock()
    return repo


def _make_service(repo: MagicMock | None = None) -> CapitalAllocationService:
    return CapitalAllocationService(repository=repo or _make_repo())


def _make_allocation(is_active: bool = False) -> CapitalAllocation:
    a = CapitalAllocation.create(
        name="Global",
        allocation_type=AllocationType.GLOBAL,
        universe_scope=UniverseScope.ALL_FNO,
        allocated_capital=Decimal("1000000"),
    )
    if is_active:
        a.activate()
    return a


class TestCreateCapitalAllocation:
    async def test_create_saves_and_appends_history(self) -> None:
        repo = _make_repo()
        service = _make_service(repo)
        a = await service.create(
            name="Test",
            allocation_type=AllocationType.GLOBAL,
            universe_scope=UniverseScope.ALL_FNO,
            allocated_capital=Decimal("500000"),
        )
        repo.save.assert_awaited_once()
        repo.append_history.assert_awaited_once()
        assert a.name == "Test"

    async def test_create_negative_capital_raises(self) -> None:
        service = _make_service()
        with pytest.raises(ValueError, match="allocated_capital"):
            await service.create(
                name="X",
                allocation_type=AllocationType.GLOBAL,
                universe_scope=UniverseScope.ALL_FNO,
                allocated_capital=Decimal("-1"),
            )


class TestActivateCapitalAllocation:
    async def test_activate_deactivates_all_first(self) -> None:
        allocation = _make_allocation()
        repo = _make_repo(by_id=allocation)
        service = _make_service(repo)
        result = await service.activate(allocation.allocation_id)
        repo.deactivate_all.assert_awaited_once()
        assert result.is_active is True

    async def test_activate_not_found_raises(self) -> None:
        repo = _make_repo(by_id=None)
        service = _make_service(repo)
        with pytest.raises(ValueError, match="not found"):
            await service.activate(uuid.uuid4())

    async def test_deactivate_appends_history(self) -> None:
        allocation = _make_allocation(is_active=True)
        repo = _make_repo(by_id=allocation)
        service = _make_service(repo)
        result = await service.deactivate(allocation.allocation_id)
        assert result.is_active is False
        repo.append_history.assert_awaited_once()


class TestUpdateCapital:
    async def test_update_capital(self) -> None:
        allocation = _make_allocation()
        repo = _make_repo(by_id=allocation)
        service = _make_service(repo)
        result = await service.update_capital(
            allocation_id=allocation.allocation_id,
            new_capital=Decimal("2000000"),
        )
        assert result.allocated_capital == Decimal("2000000")
        repo.append_history.assert_awaited_once()

    async def test_update_capital_negative_raises(self) -> None:
        allocation = _make_allocation()
        repo = _make_repo(by_id=allocation)
        service = _make_service(repo)
        with pytest.raises(ValueError):
            await service.update_capital(
                allocation_id=allocation.allocation_id,
                new_capital=Decimal("-500"),
            )

    async def test_update_mode(self) -> None:
        allocation = _make_allocation()
        repo = _make_repo(by_id=allocation)
        service = _make_service(repo)
        result = await service.update_mode(
            allocation_id=allocation.allocation_id,
            mode=CapitalSourceMode.ACCOUNT,
        )
        assert result.capital_source_mode == CapitalSourceMode.ACCOUNT
