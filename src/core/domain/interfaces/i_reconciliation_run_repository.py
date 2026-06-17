"""IReconciliationRunRepository — port for persisting reconciliation runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from uuid import UUID


@dataclass
class ReconciliationDiscrepancy:
    discrepancy_id: int
    run_id: int
    discrepancy_type: str
    order_id: UUID | None
    broker_order_id: str | None
    oms_state: str | None
    broker_state: str | None
    detail: str | None
    repair_action: str | None
    repaired: bool
    repaired_at: datetime | None
    created_at: datetime


@dataclass
class ReconciliationRunRecord:
    run_id: int
    broker_name: str
    trigger: str
    status: str
    orders_checked: int
    positions_checked: int
    fills_checked: int
    discrepancy_count: int
    rogue_count: int
    repaired_count: int
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    discrepancies: list[ReconciliationDiscrepancy] = field(default_factory=list)


@dataclass
class DiscrepancyFilter:
    discrepancy_type: str | None = None
    repaired: bool | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


class IReconciliationRunRepository(ABC):
    @abstractmethod
    async def start_run(self, broker_name: str, trigger: str) -> int:
        """Insert a new RUNNING run and return run_id."""

    @abstractmethod
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
        """Mark run COMPLETED and persist discrepancy rows."""

    @abstractmethod
    async def fail_run(self, run_id: int, error_message: str) -> None:
        """Mark run FAILED with an error message."""

    @abstractmethod
    async def list_runs(
        self,
        broker_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReconciliationRunRecord]:
        """Return paginated list of runs (newest first), without discrepancy detail."""

    @abstractmethod
    async def get_run(self, run_id: int) -> ReconciliationRunRecord | None:
        """Return a single run with its discrepancies."""

    @abstractmethod
    async def list_discrepancies(self, filters: DiscrepancyFilter) -> list[ReconciliationDiscrepancy]:
        """Query discrepancies across all runs."""

    @abstractmethod
    async def count_discrepancies(self, filters: DiscrepancyFilter) -> int: ...

    @abstractmethod
    async def mark_repaired(self, discrepancy_id: int, repair_action: str) -> None:
        """Mark a single discrepancy as repaired."""
