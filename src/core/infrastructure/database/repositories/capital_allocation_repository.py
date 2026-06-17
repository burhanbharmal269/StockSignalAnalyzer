"""SQLAlchemy implementation of ICapitalAllocationRepository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.capital_allocation import CapitalAllocation
from core.domain.enums.allocation_type import AllocationType
from core.domain.enums.capital_source_mode import CapitalSourceMode
from core.domain.enums.universe_scope import UniverseScope
from core.domain.interfaces.i_capital_allocation_repository import ICapitalAllocationRepository
from core.infrastructure.database.models.capital_framework_models import (
    AllocationHistoryOrm,
    CapitalAllocationOrm,
)


def _to_orm(allocation: CapitalAllocation) -> CapitalAllocationOrm:
    return CapitalAllocationOrm(
        allocation_id=allocation.allocation_id,
        name=allocation.name,
        allocation_type=allocation.allocation_type.value,
        universe_scope=allocation.universe_scope.value,
        capital_source_mode=allocation.capital_source_mode.value,
        allocated_capital=allocation.allocated_capital,
        allocated_margin=allocation.allocated_margin,
        strategy_type=allocation.strategy_type,
        is_active=allocation.is_active,
        description=allocation.description,
        created_at=allocation.created_at,
        updated_at=allocation.updated_at,
    )


def _to_domain(row: CapitalAllocationOrm) -> CapitalAllocation:
    return CapitalAllocation(
        allocation_id=row.allocation_id,
        name=row.name,
        allocation_type=AllocationType(row.allocation_type),
        universe_scope=UniverseScope(row.universe_scope),
        capital_source_mode=CapitalSourceMode(row.capital_source_mode),
        allocated_capital=Decimal(str(row.allocated_capital)),
        allocated_margin=Decimal(str(row.allocated_margin)) if row.allocated_margin is not None else None,
        strategy_type=row.strategy_type,
        is_active=row.is_active,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyCapitalAllocationRepository(ICapitalAllocationRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, allocation: CapitalAllocation) -> None:
        async with self._session_factory() as session:
            existing = await session.get(CapitalAllocationOrm, allocation.allocation_id)
            if existing is None:
                session.add(_to_orm(allocation))
            else:
                existing.name = allocation.name
                existing.allocation_type = allocation.allocation_type.value
                existing.universe_scope = allocation.universe_scope.value
                existing.capital_source_mode = allocation.capital_source_mode.value
                existing.allocated_capital = allocation.allocated_capital
                existing.allocated_margin = allocation.allocated_margin
                existing.strategy_type = allocation.strategy_type
                existing.is_active = allocation.is_active
                existing.description = allocation.description
                existing.updated_at = allocation.updated_at
            await session.commit()

    async def get_by_id(self, allocation_id: uuid.UUID) -> CapitalAllocation | None:
        async with self._session_factory() as session:
            row = await session.get(CapitalAllocationOrm, allocation_id)
            return _to_domain(row) if row else None

    async def get_active(self) -> CapitalAllocation | None:
        async with self._session_factory() as session:
            stmt = (
                select(CapitalAllocationOrm)
                .where(CapitalAllocationOrm.is_active.is_(True))
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def list_all(self) -> list[CapitalAllocation]:
        async with self._session_factory() as session:
            stmt = select(CapitalAllocationOrm).order_by(CapitalAllocationOrm.created_at)
            result = await session.execute(stmt)
            return [_to_domain(r) for r in result.scalars().all()]

    async def deactivate_all(self) -> None:
        async with self._session_factory() as session:
            stmt = update(CapitalAllocationOrm).values(is_active=False)
            await session.execute(stmt)
            await session.commit()

    async def append_history(
        self,
        allocation_id: uuid.UUID,
        change_type: str,
        previous_capital: object,
        new_capital: object,
        changed_by: str = "system",
        notes: str = "",
    ) -> None:
        async with self._session_factory() as session:
            row = AllocationHistoryOrm(
                allocation_id=allocation_id,
                change_type=change_type,
                previous_capital=Decimal(str(previous_capital)) if previous_capital is not None else None,
                new_capital=Decimal(str(new_capital)) if new_capital is not None else None,
                changed_by=changed_by,
                notes=notes,
                changed_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
