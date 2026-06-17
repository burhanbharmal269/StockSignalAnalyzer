"""SqlAlchemyRampUpRepository — persists live trading ramp-up state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.live_trading_safety_service import RampUpState
from core.domain.interfaces.i_ramp_up_repository import IRampUpRepository
from core.infrastructure.database.models.reconciliation_models import LiveTradingRampUpOrm

_STAGE_CAPITALS = {1: Decimal("5000"), 2: Decimal("10000"), 3: Decimal("25000"), 4: Decimal("50000")}


class SqlAlchemyRampUpRepository(IRampUpRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as s:
            async with s.begin():
                yield s

    async def get_current(self) -> RampUpState | None:
        async with self._factory() as s:
            stmt = select(LiveTradingRampUpOrm).order_by(LiveTradingRampUpOrm.ramp_id.desc()).limit(1)
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return self._to_domain(row)

    async def create_initial(self) -> RampUpState:
        async with self._session() as s:
            row = LiveTradingRampUpOrm(
                current_stage=1,
                stage_capital=_STAGE_CAPITALS[1],
                stage_entered_at=datetime.now(UTC),
                locked=False,
            )
            s.add(row)
            await s.flush()
            return self._to_domain(row)

    async def promote_stage(self, performance_snapshot: dict) -> RampUpState:
        async with self._session() as s:
            stmt = select(LiveTradingRampUpOrm).order_by(LiveTradingRampUpOrm.ramp_id.desc()).limit(1)
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is None:
                raise ValueError("No ramp-up state to promote")
            next_stage = min(row.current_stage + 1, 4)
            row.current_stage = next_stage
            row.stage_capital = _STAGE_CAPITALS[next_stage]
            row.stage_entered_at = datetime.now(UTC)
            row.promoted_at = datetime.now(UTC)
            row.performance_snapshot = performance_snapshot
            row.updated_at = datetime.now(UTC)
            return self._to_domain(row)

    async def lock(self, reason: str) -> None:
        async with self._session() as s:
            stmt = select(LiveTradingRampUpOrm).order_by(LiveTradingRampUpOrm.ramp_id.desc()).limit(1)
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is not None:
                row.locked = True
                row.lock_reason = reason
                row.updated_at = datetime.now(UTC)

    async def unlock(self) -> None:
        async with self._session() as s:
            stmt = select(LiveTradingRampUpOrm).order_by(LiveTradingRampUpOrm.ramp_id.desc()).limit(1)
            row = (await s.execute(stmt)).scalar_one_or_none()
            if row is not None:
                row.locked = False
                row.lock_reason = None
                row.updated_at = datetime.now(UTC)

    @staticmethod
    def _to_domain(r: LiveTradingRampUpOrm) -> RampUpState:
        return RampUpState(
            ramp_id=r.ramp_id,
            current_stage=r.current_stage,
            stage_capital=r.stage_capital,
            stage_entered_at=r.stage_entered_at,
            promoted_at=r.promoted_at,
            locked=r.locked,
            lock_reason=r.lock_reason,
            performance_snapshot=r.performance_snapshot,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
