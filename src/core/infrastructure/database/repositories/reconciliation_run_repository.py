"""SqlAlchemyReconciliationRunRepository — persists reconciliation runs and discrepancies."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_reconciliation_run_repository import (
    DiscrepancyFilter,
    IReconciliationRunRepository,
    ReconciliationDiscrepancy,
    ReconciliationRunRecord,
)
from core.infrastructure.database.models.reconciliation_models import (
    ReconciliationDiscrepancyOrm,
    ReconciliationRunOrm,
)

_log = logging.getLogger(__name__)


class SqlAlchemyReconciliationRunRepository(IReconciliationRunRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as s:
            async with s.begin():
                yield s

    async def start_run(self, broker_name: str, trigger: str) -> int:
        async with self._session() as s:
            row = ReconciliationRunOrm(
                broker_name=broker_name,
                trigger=trigger,
                status="RUNNING",
                started_at=datetime.now(UTC),
            )
            s.add(row)
            await s.flush()
            return row.run_id

    async def complete_run(
        self,
        run_id: int,
        orders_checked: int,
        positions_checked: int,
        fills_checked: int,
        discrepancy_count: int,
        rogue_count: int,
        repaired_count: int,
        discrepancies: list[dict],
    ) -> None:
        async with self._session() as s:
            await s.execute(
                update(ReconciliationRunOrm)
                .where(ReconciliationRunOrm.run_id == run_id)
                .values(
                    status="COMPLETED",
                    completed_at=datetime.now(UTC),
                    orders_checked=orders_checked,
                    positions_checked=positions_checked,
                    fills_checked=fills_checked,
                    discrepancy_count=discrepancy_count,
                    rogue_count=rogue_count,
                    repaired_count=repaired_count,
                )
            )
            for d in discrepancies:
                row = ReconciliationDiscrepancyOrm(
                    run_id=run_id,
                    discrepancy_type=d.get("type", "UNKNOWN"),
                    order_id=d.get("order_id"),
                    broker_order_id=d.get("broker_order_id"),
                    oms_state=d.get("oms_state"),
                    broker_state=d.get("broker_state"),
                    detail=d.get("detail"),
                    repair_action=d.get("repair_action"),
                    repaired=bool(d.get("repaired", False)),
                    repaired_at=d.get("repaired_at"),
                    created_at=datetime.now(UTC),
                )
                s.add(row)

    async def fail_run(self, run_id: int, error_message: str) -> None:
        async with self._session() as s:
            await s.execute(
                update(ReconciliationRunOrm)
                .where(ReconciliationRunOrm.run_id == run_id)
                .values(
                    status="FAILED",
                    completed_at=datetime.now(UTC),
                    error_message=error_message[:2000],
                )
            )

    async def list_runs(
        self,
        broker_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReconciliationRunRecord]:
        async with self._factory() as s:
            stmt = select(ReconciliationRunOrm).order_by(
                ReconciliationRunOrm.started_at.desc()
            )
            if broker_name:
                stmt = stmt.where(ReconciliationRunOrm.broker_name == broker_name)
            stmt = stmt.limit(limit).offset(offset)
            rows = (await s.execute(stmt)).scalars().all()
            return [self._orm_to_run_record(r) for r in rows]

    async def get_run(self, run_id: int) -> ReconciliationRunRecord | None:
        async with self._factory() as s:
            row = await s.get(ReconciliationRunOrm, run_id)
            if row is None:
                return None
            record = self._orm_to_run_record(row)
            # fetch discrepancies
            disc_stmt = (
                select(ReconciliationDiscrepancyOrm)
                .where(ReconciliationDiscrepancyOrm.run_id == run_id)
                .order_by(ReconciliationDiscrepancyOrm.created_at)
            )
            disc_rows = (await s.execute(disc_stmt)).scalars().all()
            record.discrepancies = [self._orm_to_discrepancy(d) for d in disc_rows]
            return record

    async def list_discrepancies(self, filters: DiscrepancyFilter) -> list[ReconciliationDiscrepancy]:
        async with self._factory() as s:
            stmt = select(ReconciliationDiscrepancyOrm).order_by(
                ReconciliationDiscrepancyOrm.created_at.desc()
            )
            stmt = self._apply_filters(stmt, filters)
            stmt = stmt.limit(filters.limit).offset(filters.offset)
            rows = (await s.execute(stmt)).scalars().all()
            return [self._orm_to_discrepancy(r) for r in rows]

    async def count_discrepancies(self, filters: DiscrepancyFilter) -> int:
        async with self._factory() as s:
            stmt = select(func.count()).select_from(ReconciliationDiscrepancyOrm)
            stmt = self._apply_filters(stmt, filters)
            return (await s.execute(stmt)).scalar_one()

    async def mark_repaired(self, discrepancy_id: int, repair_action: str) -> None:
        async with self._session() as s:
            await s.execute(
                update(ReconciliationDiscrepancyOrm)
                .where(ReconciliationDiscrepancyOrm.discrepancy_id == discrepancy_id)
                .values(
                    repaired=True,
                    repair_action=repair_action,
                    repaired_at=datetime.now(UTC),
                )
            )

    def _apply_filters(self, stmt, filters: DiscrepancyFilter):
        if filters.discrepancy_type:
            stmt = stmt.where(
                ReconciliationDiscrepancyOrm.discrepancy_type == filters.discrepancy_type
            )
        if filters.repaired is not None:
            stmt = stmt.where(ReconciliationDiscrepancyOrm.repaired == filters.repaired)
        if filters.since:
            stmt = stmt.where(ReconciliationDiscrepancyOrm.created_at >= filters.since)
        if filters.until:
            stmt = stmt.where(ReconciliationDiscrepancyOrm.created_at <= filters.until)
        return stmt

    @staticmethod
    def _orm_to_run_record(r: ReconciliationRunOrm) -> ReconciliationRunRecord:
        return ReconciliationRunRecord(
            run_id=r.run_id,
            broker_name=r.broker_name,
            trigger=r.trigger,
            status=r.status,
            orders_checked=r.orders_checked,
            positions_checked=r.positions_checked,
            fills_checked=r.fills_checked,
            discrepancy_count=r.discrepancy_count,
            rogue_count=r.rogue_count,
            repaired_count=r.repaired_count,
            error_message=r.error_message,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )

    @staticmethod
    def _orm_to_discrepancy(d: ReconciliationDiscrepancyOrm) -> ReconciliationDiscrepancy:
        return ReconciliationDiscrepancy(
            discrepancy_id=d.discrepancy_id,
            run_id=d.run_id,
            discrepancy_type=d.discrepancy_type,
            order_id=d.order_id,
            broker_order_id=d.broker_order_id,
            oms_state=d.oms_state,
            broker_state=d.broker_state,
            detail=d.detail,
            repair_action=d.repair_action,
            repaired=d.repaired,
            repaired_at=d.repaired_at,
            created_at=d.created_at,
        )
