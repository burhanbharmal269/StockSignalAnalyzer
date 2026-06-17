"""SqlAlchemy implementation of IBrokerOrderMappingRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_broker_order_mapping_repository import (
    BrokerOrderMapping,
    IBrokerOrderMappingRepository,
)
from core.infrastructure.database.models.broker_execution_models import BrokerOrderMappingOrm


class SqlAlchemyBrokerOrderMappingRepository(IBrokerOrderMappingRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _to_domain(self, row: BrokerOrderMappingOrm) -> BrokerOrderMapping:
        return BrokerOrderMapping(
            internal_order_id=row.internal_order_id,
            broker_order_id=row.broker_order_id,
            broker_name=row.broker_name,
            status=row.status,
            attempt_count=row.attempt_count,
            last_error=row.last_error,
            last_retry_at=row.last_retry_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def upsert(self, mapping: BrokerOrderMapping) -> None:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            pg_insert(BrokerOrderMappingOrm)
            .values(
                internal_order_id=mapping.internal_order_id,
                broker_order_id=mapping.broker_order_id,
                broker_name=mapping.broker_name,
                status=mapping.status,
                attempt_count=mapping.attempt_count,
                last_error=mapping.last_error,
                last_retry_at=mapping.last_retry_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["internal_order_id"],
                set_={
                    "broker_order_id": mapping.broker_order_id,
                    "status": mapping.status,
                    "attempt_count": mapping.attempt_count,
                    "last_error": mapping.last_error,
                    "last_retry_at": mapping.last_retry_at,
                    "updated_at": now,
                },
            )
        )
        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def get_by_internal_id(self, internal_order_id: UUID) -> BrokerOrderMapping | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BrokerOrderMappingOrm).where(
                    BrokerOrderMappingOrm.internal_order_id == internal_order_id
                )
            )
            row = result.scalar_one_or_none()
            return self._to_domain(row) if row else None

    async def get_pending(self) -> list[BrokerOrderMapping]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BrokerOrderMappingOrm).where(
                    BrokerOrderMappingOrm.status == "PENDING"
                )
            )
            return [self._to_domain(r) for r in result.scalars().all()]

    async def mark_submitted(self, internal_order_id: UUID, broker_order_id: str) -> None:
        now = datetime.now(tz=timezone.utc)
        async with self._session_factory() as session:
            await session.execute(
                update(BrokerOrderMappingOrm)
                .where(BrokerOrderMappingOrm.internal_order_id == internal_order_id)
                .values(
                    broker_order_id=broker_order_id,
                    status="SUBMITTED",
                    updated_at=now,
                )
            )
            await session.commit()

    async def mark_failed(self, internal_order_id: UUID, error: str, attempt_count: int) -> None:
        now = datetime.now(tz=timezone.utc)
        async with self._session_factory() as session:
            await session.execute(
                update(BrokerOrderMappingOrm)
                .where(BrokerOrderMappingOrm.internal_order_id == internal_order_id)
                .values(
                    status="FAILED",
                    last_error=error,
                    attempt_count=attempt_count,
                    last_retry_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
