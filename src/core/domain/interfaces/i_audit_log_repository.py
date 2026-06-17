"""IAuditLogRepository — domain port for audit log persistence and search."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class AuditLogEntry:
    action: str
    entity_type: str
    entity_id: str
    user_id: UUID | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    metadata: dict | None = None
    ip_address: str | None = None


@dataclass
class AuditLogRecord:
    id: int
    action: str
    entity_type: str
    entity_id: str
    user_id: UUID | None
    old_value: dict | None
    new_value: dict | None
    metadata: dict | None
    ip_address: str | None
    created_at: datetime


@dataclass
class AuditLogFilter:
    action: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    user_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


class IAuditLogRepository(abc.ABC):
    @abc.abstractmethod
    async def append(self, entry: AuditLogEntry) -> None: ...

    @abc.abstractmethod
    async def search(self, filters: AuditLogFilter) -> list[AuditLogRecord]: ...

    @abc.abstractmethod
    async def count(self, filters: AuditLogFilter) -> int: ...
