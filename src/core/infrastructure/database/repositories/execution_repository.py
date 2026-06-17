"""SQLAlchemy implementation of IExecutionRepository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_execution_repository import IExecutionRepository
from core.domain.value_objects.fill import Fill
from core.domain.value_objects.price import Price
from core.infrastructure.database.models.order_models import ExecutionOrm


def _to_orm(fill: Fill) -> ExecutionOrm:
    return ExecutionOrm(
        fill_id=fill.fill_id,
        order_id=fill.order_id,
        broker_order_id=fill.broker_order_id,
        exchange_trade_id=fill.exchange_trade_id,
        filled_quantity=fill.filled_quantity,
        fill_price=fill.fill_price.value,
        fill_time=fill.fill_time,
        trading_mode=fill.trading_mode,
    )


def _to_domain(row: ExecutionOrm) -> Fill:
    return Fill(
        fill_id=row.fill_id,
        order_id=row.order_id,
        broker_order_id=row.broker_order_id,
        exchange_trade_id=row.exchange_trade_id,
        filled_quantity=row.filled_quantity,
        fill_price=Price(row.fill_price),
        fill_time=row.fill_time,
        trading_mode=row.trading_mode,
    )


class SqlAlchemyExecutionRepository(IExecutionRepository):
    """Append-only fill records — fills are never modified."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, fill: Fill) -> None:
        async with self._session_factory() as session:
            session.add(_to_orm(fill))
            await session.commit()

    async def get_by_order_id(self, order_id: UUID) -> list[Fill]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExecutionOrm)
                .where(ExecutionOrm.order_id == order_id)
                .order_by(ExecutionOrm.fill_time)
            )
            return [_to_domain(r) for r in result.scalars()]

    async def get_by_id(self, fill_id: UUID) -> Fill | None:
        async with self._session_factory() as session:
            row = await session.get(ExecutionOrm, fill_id)
            return _to_domain(row) if row else None
