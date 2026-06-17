"""Audit log router — searchable audit trail.

GET /api/v1/audit         — search audit logs (admin only)
GET /api/v1/audit/{id}    — (future: single record fetch)

Query parameters:
  action       — filter by action string (USER_LOGIN, SIGNAL_APPROVED, etc.)
  entity_type  — filter by entity_type (signal, order, position, etc.)
  entity_id    — filter by specific entity ID
  user_id      — filter by user UUID
  since        — ISO-8601 timestamp lower bound
  until        — ISO-8601 timestamp upper bound
  limit        — max records (1-500, default 100)
  offset       — pagination offset
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from container import ApplicationContainer
from core.domain.interfaces.i_audit_log_repository import AuditLogFilter, IAuditLogRepository
from core.presentation.api.v1.dependencies.auth import require_admin
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


class AuditLogRecordResponse(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: str
    user_id: str | None
    old_value: dict | None
    new_value: dict | None
    metadata: dict | None
    ip_address: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    records: list[AuditLogRecordResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditLogListResponse, summary="Search audit logs (admin only)")
@inject
async def search_audit_logs(
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    audit_log_repository: IAuditLogRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.audit_log_repository]
    ),
) -> AuditLogListResponse:
    filters = AuditLogFilter(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    records = await audit_log_repository.search(filters)
    total = await audit_log_repository.count(filters)

    return AuditLogListResponse(
        records=[
            AuditLogRecordResponse(
                id=r.id,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                user_id=str(r.user_id) if r.user_id else None,
                old_value=r.old_value,
                new_value=r.new_value,
                metadata=r.metadata,
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
