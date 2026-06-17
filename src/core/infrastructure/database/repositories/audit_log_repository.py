"""SqlAlchemy implementation of IAuditLogRepository.

Appends to audit_logs (appended columns from migration 007_phase18).
No UPDATE or DELETE is ever issued on this table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.interfaces.i_audit_log_repository import (
    AuditLogEntry,
    AuditLogFilter,
    AuditLogRecord,
    IAuditLogRepository,
)
from core.infrastructure.database.models.user_models import AuditLogOrm


class SqlAlchemyAuditLogRepository(IAuditLogRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _to_record(self, row: AuditLogOrm) -> AuditLogRecord:
        return AuditLogRecord(
            id=row.id,
            action=row.action,
            entity_type=getattr(row, "entity_type", None) or row.resource_type,
            entity_id=getattr(row, "entity_id", None) or row.resource_id or "",
            user_id=row.user_id,
            old_value=getattr(row, "old_value", None),
            new_value=getattr(row, "new_value", None),
            metadata=getattr(row, "metadata", None) or row.details,
            ip_address=row.ip_address,
            created_at=row.timestamp,
        )

    async def append(self, entry: AuditLogEntry) -> None:
        now = datetime.now(tz=timezone.utc)
        row = AuditLogOrm(
            timestamp=now,
            user_id=entry.user_id,
            action=entry.action,
            resource_type=entry.entity_type,
            resource_id=entry.entity_id,
            ip_address=entry.ip_address,
            details=entry.metadata,
        )
        # Set Phase 18 columns (may not exist in ORM if migration not run yet; use setattr)
        for col, val in [
            ("entity_type", entry.entity_type),
            ("entity_id", entry.entity_id),
            ("old_value", entry.old_value),
            ("new_value", entry.new_value),
            ("metadata", entry.metadata),
        ]:
            try:
                setattr(row, col, val)
            except Exception:  # noqa: BLE001
                pass

        async with self._session_factory() as session:
            session.add(row)
            await session.commit()

    async def search(self, filters: AuditLogFilter) -> list[AuditLogRecord]:
        stmt = select(AuditLogOrm).order_by(AuditLogOrm.timestamp.desc())
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.limit(filters.limit).offset(filters.offset)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return [self._to_record(r) for r in result.scalars().all()]

    async def count(self, filters: AuditLogFilter) -> int:
        stmt = select(func.count()).select_from(AuditLogOrm)
        stmt = self._apply_filters(stmt, filters)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    def _apply_filters(self, stmt, filters: AuditLogFilter):
        if filters.action:
            stmt = stmt.where(AuditLogOrm.action == filters.action)
        if filters.entity_type:
            stmt = stmt.where(AuditLogOrm.resource_type == filters.entity_type)
        if filters.entity_id:
            stmt = stmt.where(AuditLogOrm.resource_id == filters.entity_id)
        if filters.user_id:
            stmt = stmt.where(AuditLogOrm.user_id == filters.user_id)
        if filters.since:
            stmt = stmt.where(AuditLogOrm.timestamp >= filters.since)
        if filters.until:
            stmt = stmt.where(AuditLogOrm.timestamp <= filters.until)
        return stmt
