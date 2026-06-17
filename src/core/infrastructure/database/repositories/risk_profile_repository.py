"""SQLAlchemy implementation of IRiskProfileRepository."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.risk_profile import RiskProfile
from core.domain.enums.risk_profile_type import RiskProfileType
from core.domain.enums.universe_scope import UniverseScope
from core.domain.interfaces.i_risk_profile_repository import IRiskProfileRepository
from core.infrastructure.database.models.capital_framework_models import RiskProfileOrm


def _to_orm(profile: RiskProfile) -> RiskProfileOrm:
    return RiskProfileOrm(
        profile_id=profile.profile_id,
        name=profile.name,
        profile_type=profile.profile_type.value,
        universe_scope=profile.universe_scope.value,
        risk_per_trade_pct=profile.risk_per_trade_pct,
        max_open_positions=profile.max_open_positions,
        daily_loss_pct=profile.daily_loss_pct,
        weekly_loss_pct=profile.weekly_loss_pct,
        drawdown_pct=profile.drawdown_pct,
        max_position_size_pct=profile.max_position_size_pct,
        min_position_size_lots=profile.min_position_size_lots,
        is_active=profile.is_active,
        description=profile.description,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _to_domain(row: RiskProfileOrm) -> RiskProfile:
    return RiskProfile(
        profile_id=row.profile_id,
        name=row.name,
        profile_type=RiskProfileType(row.profile_type),
        universe_scope=UniverseScope(row.universe_scope),
        risk_per_trade_pct=Decimal(str(row.risk_per_trade_pct)),
        max_open_positions=row.max_open_positions,
        daily_loss_pct=Decimal(str(row.daily_loss_pct)),
        weekly_loss_pct=Decimal(str(row.weekly_loss_pct)),
        drawdown_pct=Decimal(str(row.drawdown_pct)),
        max_position_size_pct=Decimal(str(row.max_position_size_pct)),
        min_position_size_lots=row.min_position_size_lots,
        is_active=row.is_active,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyRiskProfileRepository(IRiskProfileRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, profile: RiskProfile) -> None:
        async with self._session_factory() as session:
            existing = await session.get(RiskProfileOrm, profile.profile_id)
            if existing is None:
                session.add(_to_orm(profile))
            else:
                existing.name = profile.name
                existing.profile_type = profile.profile_type.value
                existing.universe_scope = profile.universe_scope.value
                existing.risk_per_trade_pct = profile.risk_per_trade_pct
                existing.max_open_positions = profile.max_open_positions
                existing.daily_loss_pct = profile.daily_loss_pct
                existing.weekly_loss_pct = profile.weekly_loss_pct
                existing.drawdown_pct = profile.drawdown_pct
                existing.max_position_size_pct = profile.max_position_size_pct
                existing.min_position_size_lots = profile.min_position_size_lots
                existing.is_active = profile.is_active
                existing.description = profile.description
                existing.updated_at = profile.updated_at
            await session.commit()

    async def get_by_id(self, profile_id: uuid.UUID) -> RiskProfile | None:
        async with self._session_factory() as session:
            row = await session.get(RiskProfileOrm, profile_id)
            return _to_domain(row) if row else None

    async def get_active(self) -> RiskProfile | None:
        async with self._session_factory() as session:
            stmt = select(RiskProfileOrm).where(RiskProfileOrm.is_active.is_(True)).limit(1)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def list_all(self) -> list[RiskProfile]:
        async with self._session_factory() as session:
            stmt = select(RiskProfileOrm).order_by(RiskProfileOrm.created_at)
            result = await session.execute(stmt)
            return [_to_domain(r) for r in result.scalars().all()]

    async def deactivate_all(self) -> None:
        async with self._session_factory() as session:
            stmt = update(RiskProfileOrm).values(is_active=False)
            await session.execute(stmt)
            await session.commit()
