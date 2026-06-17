"""CapitalAllocationService — CRUD and lifecycle for CapitalAllocation entities."""

from __future__ import annotations

import uuid
from decimal import Decimal

from core.domain.entities.capital_allocation import CapitalAllocation
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.universe_scope import UniverseScope
from core.domain.interfaces.i_capital_allocation_repository import ICapitalAllocationRepository
from core.infrastructure.logging.setup import get_logger

_log = get_logger(__name__)


class CapitalAllocationService:
    def __init__(self, repository: ICapitalAllocationRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_id(self, allocation_id: uuid.UUID) -> CapitalAllocation | None:
        return await self._repo.get_by_id(allocation_id)

    async def get_active(self) -> CapitalAllocation | None:
        return await self._repo.get_active()

    async def list_all(self) -> list[CapitalAllocation]:
        return await self._repo.list_all()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        allocation_type: AllocationType,
        universe_scope: UniverseScope,
        allocated_capital: Decimal,
        *,
        capital_source_mode: CapitalSourceMode = CapitalSourceMode.HYBRID,
        allocated_margin: Decimal | None = None,
        strategy_type: str | None = None,
        description: str = "",
    ) -> CapitalAllocation:
        self._validate(allocated_capital=allocated_capital, allocated_margin=allocated_margin)
        allocation = CapitalAllocation.create(
            name=name,
            allocation_type=allocation_type,
            universe_scope=universe_scope,
            allocated_capital=allocated_capital,
            capital_source_mode=capital_source_mode,
            allocated_margin=allocated_margin,
            strategy_type=strategy_type,
            description=description,
        )
        await self._repo.save(allocation)
        await self._repo.append_history(
            allocation_id=allocation.allocation_id,
            change_type="CREATED",
            previous_capital=None,
            new_capital=allocated_capital,
            changed_by="system",
            notes=f"Initial allocation: {name}",
        )
        _log.info(
            "capital_allocation.created",
            allocation_id=str(allocation.allocation_id),
            name=name,
            allocated_capital=str(allocated_capital),
        )
        return allocation

    async def activate(self, allocation_id: uuid.UUID, changed_by: str = "system") -> CapitalAllocation:
        allocation = await self._repo.get_by_id(allocation_id)
        if allocation is None:
            msg = f"CapitalAllocation {allocation_id} not found"
            raise ValueError(msg)
        await self._repo.deactivate_all()
        allocation.activate()
        await self._repo.save(allocation)
        await self._repo.append_history(
            allocation_id=allocation_id,
            change_type="ACTIVATED",
            previous_capital=None,
            new_capital=allocation.allocated_capital,
            changed_by=changed_by,
        )
        _log.info("capital_allocation.activated", allocation_id=str(allocation_id))
        return allocation

    async def deactivate(self, allocation_id: uuid.UUID, changed_by: str = "system") -> CapitalAllocation:
        allocation = await self._repo.get_by_id(allocation_id)
        if allocation is None:
            msg = f"CapitalAllocation {allocation_id} not found"
            raise ValueError(msg)
        prev_capital = allocation.allocated_capital
        allocation.deactivate()
        await self._repo.save(allocation)
        await self._repo.append_history(
            allocation_id=allocation_id,
            change_type="DEACTIVATED",
            previous_capital=prev_capital,
            new_capital=None,
            changed_by=changed_by,
        )
        _log.info("capital_allocation.deactivated", allocation_id=str(allocation_id))
        return allocation

    async def update_capital(
        self,
        allocation_id: uuid.UUID,
        new_capital: Decimal,
        new_margin: Decimal | None = None,
        changed_by: str = "system",
        notes: str = "",
    ) -> CapitalAllocation:
        self._validate(allocated_capital=new_capital, allocated_margin=new_margin)
        allocation = await self._repo.get_by_id(allocation_id)
        if allocation is None:
            msg = f"CapitalAllocation {allocation_id} not found"
            raise ValueError(msg)
        prev_capital = allocation.allocated_capital
        prev_margin = allocation.allocated_margin
        allocation.update_capital(new_capital, new_margin)
        await self._repo.save(allocation)
        await self._repo.append_history(
            allocation_id=allocation_id,
            change_type="CAPITAL_UPDATED",
            previous_capital=prev_capital,
            new_capital=new_capital,
            changed_by=changed_by,
            notes=notes,
        )
        _log.info(
            "capital_allocation.capital_updated",
            allocation_id=str(allocation_id),
            previous=str(prev_capital),
            new=str(new_capital),
        )
        return allocation

    async def update_mode(
        self,
        allocation_id: uuid.UUID,
        mode: CapitalSourceMode,
        changed_by: str = "system",
    ) -> CapitalAllocation:
        allocation = await self._repo.get_by_id(allocation_id)
        if allocation is None:
            msg = f"CapitalAllocation {allocation_id} not found"
            raise ValueError(msg)
        allocation.update_mode(mode)
        await self._repo.save(allocation)
        await self._repo.append_history(
            allocation_id=allocation_id,
            change_type="MODE_CHANGED",
            previous_capital=allocation.allocated_capital,
            new_capital=allocation.allocated_capital,
            changed_by=changed_by,
            notes=f"mode={mode.value}",
        )
        _log.info(
            "capital_allocation.mode_updated",
            allocation_id=str(allocation_id),
            mode=mode.value,
        )
        return allocation

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(allocated_capital: Decimal, allocated_margin: Decimal | None) -> None:
        errors: list[str] = []
        if allocated_capital < Decimal(0):
            errors.append("allocated_capital must be >= 0")
        if allocated_margin is not None and allocated_margin < Decimal(0):
            errors.append("allocated_margin must be >= 0")
        if errors:
            raise ValueError("; ".join(errors))
