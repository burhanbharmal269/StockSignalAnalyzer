"""IBrokerOrderMappingRepository — domain port for broker order ID correlation."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class BrokerOrderMapping:
    internal_order_id: UUID
    broker_order_id: str
    broker_name: str
    status: str
    attempt_count: int
    last_error: str | None
    last_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IBrokerOrderMappingRepository(abc.ABC):
    @abc.abstractmethod
    async def upsert(self, mapping: BrokerOrderMapping) -> None: ...

    @abc.abstractmethod
    async def get_by_internal_id(self, internal_order_id: UUID) -> BrokerOrderMapping | None: ...

    @abc.abstractmethod
    async def get_pending(self) -> list[BrokerOrderMapping]: ...

    @abc.abstractmethod
    async def mark_submitted(self, internal_order_id: UUID, broker_order_id: str) -> None: ...

    @abc.abstractmethod
    async def mark_failed(self, internal_order_id: UUID, error: str, attempt_count: int) -> None: ...
