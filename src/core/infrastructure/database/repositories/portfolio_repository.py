"""SQLAlchemy implementation of IPortfolioRepository."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.portfolio import Portfolio
from core.domain.enums.portfolio_type import PortfolioType
from core.domain.interfaces.i_portfolio_repository import IPortfolioRepository
from core.infrastructure.database.models.capital_framework_models import PortfolioOrm


def _to_orm(portfolio: Portfolio) -> PortfolioOrm:
    return PortfolioOrm(
        portfolio_id=portfolio.portfolio_id,
        name=portfolio.name,
        portfolio_type=portfolio.portfolio_type.value,
        risk_profile_id=portfolio.risk_profile_id,
        allocation_id=portfolio.allocation_id,
        owner_user_id=portfolio.owner_user_id,
        is_active=portfolio.is_active,
        description=portfolio.description,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )


def _to_domain(row: PortfolioOrm) -> Portfolio:
    return Portfolio(
        portfolio_id=row.portfolio_id,
        name=row.name,
        portfolio_type=PortfolioType(row.portfolio_type),
        risk_profile_id=row.risk_profile_id,
        allocation_id=row.allocation_id,
        owner_user_id=row.owner_user_id,
        is_active=row.is_active,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyPortfolioRepository(IPortfolioRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, portfolio: Portfolio) -> None:
        async with self._session_factory() as session:
            existing = await session.get(PortfolioOrm, portfolio.portfolio_id)
            if existing is None:
                session.add(_to_orm(portfolio))
            else:
                existing.name = portfolio.name
                existing.portfolio_type = portfolio.portfolio_type.value
                existing.risk_profile_id = portfolio.risk_profile_id
                existing.allocation_id = portfolio.allocation_id
                existing.owner_user_id = portfolio.owner_user_id
                existing.is_active = portfolio.is_active
                existing.description = portfolio.description
                existing.updated_at = portfolio.updated_at
            await session.commit()

    async def get_by_id(self, portfolio_id: uuid.UUID) -> Portfolio | None:
        async with self._session_factory() as session:
            row = await session.get(PortfolioOrm, portfolio_id)
            return _to_domain(row) if row else None

    async def get_active(self) -> Portfolio | None:
        async with self._session_factory() as session:
            stmt = select(PortfolioOrm).where(PortfolioOrm.is_active.is_(True)).limit(1)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_active_by_type(self, portfolio_type: PortfolioType) -> Portfolio | None:
        async with self._session_factory() as session:
            stmt = (
                select(PortfolioOrm)
                .where(
                    PortfolioOrm.is_active.is_(True),
                    PortfolioOrm.portfolio_type == portfolio_type.value,
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def list_all(self) -> list[Portfolio]:
        async with self._session_factory() as session:
            stmt = select(PortfolioOrm).order_by(PortfolioOrm.created_at)
            result = await session.execute(stmt)
            return [_to_domain(r) for r in result.scalars().all()]

    async def deactivate_all(self) -> None:
        async with self._session_factory() as session:
            stmt = update(PortfolioOrm).values(is_active=False)
            await session.execute(stmt)
            await session.commit()
