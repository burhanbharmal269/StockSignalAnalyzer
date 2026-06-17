"""Tests for reconciliation engine persistence and auto-repair."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.oms.reconciliation_service import (
    ReconciliationResult,
    ReconciliationService,
)
from core.domain.interfaces.i_reconciliation_run_repository import (
    DiscrepancyFilter,
    IReconciliationRunRepository,
    ReconciliationDiscrepancy,
    ReconciliationRunRecord,
)


class FakeRunRepository(IReconciliationRunRepository):
    def __init__(self) -> None:
        self._runs: list[ReconciliationRunRecord] = []
        self._next_run_id = 1
        self._discrepancies: list[dict] = []

    async def start_run(self, broker_name: str, trigger: str) -> int:
        run_id = self._next_run_id
        self._next_run_id += 1
        self._runs.append(
            ReconciliationRunRecord(
                run_id=run_id,
                broker_name=broker_name,
                trigger=trigger,
                status="RUNNING",
                orders_checked=0,
                positions_checked=0,
                fills_checked=0,
                discrepancy_count=0,
                rogue_count=0,
                repaired_count=0,
                error_message=None,
                started_at=datetime.now(UTC),
                completed_at=None,
            )
        )
        return run_id

    async def complete_run(self, run_id, orders_checked, positions_checked, fills_checked,
                           discrepancy_count, rogue_count, repaired_count, discrepancies):
        for r in self._runs:
            if r.run_id == run_id:
                r.status = "COMPLETED"
                r.orders_checked = orders_checked
                r.positions_checked = positions_checked
                r.fills_checked = fills_checked
                r.discrepancy_count = discrepancy_count
                r.rogue_count = rogue_count
                r.repaired_count = repaired_count
                r.completed_at = datetime.now(UTC)
        self._discrepancies.extend(discrepancies)

    async def fail_run(self, run_id: int, error_message: str) -> None:
        for r in self._runs:
            if r.run_id == run_id:
                r.status = "FAILED"
                r.error_message = error_message

    async def list_runs(self, broker_name=None, limit=50, offset=0):
        return self._runs[-limit:]

    async def get_run(self, run_id):
        for r in self._runs:
            if r.run_id == run_id:
                return r
        return None

    async def list_discrepancies(self, filters: DiscrepancyFilter):
        return []

    async def count_discrepancies(self, filters: DiscrepancyFilter) -> int:
        return 0

    async def mark_repaired(self, discrepancy_id: int, repair_action: str) -> None:
        pass


def _make_service(run_repo=None):
    order_repo = AsyncMock()
    order_repo.get_by_state = AsyncMock(return_value=[])
    position_repo = AsyncMock()
    position_repo.get_open_positions = AsyncMock(return_value=[])
    broker = AsyncMock()
    broker.get_orders = AsyncMock(return_value=[])
    broker.get_positions = AsyncMock(return_value=[])
    broker.get_trades = AsyncMock(return_value=[])
    kill_switch = AsyncMock()
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()

    return ReconciliationService(
        order_repository=order_repo,
        position_repository=position_repo,
        broker=broker,
        kill_switch_repository=kill_switch,
        event_bus=event_bus,
        execution_repository=None,
        run_repository=run_repo,
        broker_name="test_broker",
    )


@pytest.mark.asyncio
async def test_run_creates_persisted_record() -> None:
    repo = FakeRunRepository()
    service = _make_service(run_repo=repo)
    fake_session = object()

    result = await service.run(fake_session, trigger="MANUAL")

    assert len(repo._runs) == 1
    run = repo._runs[0]
    assert run.status == "COMPLETED"
    assert run.trigger == "MANUAL"
    assert run.broker_name == "test_broker"


@pytest.mark.asyncio
async def test_run_without_repo_still_works() -> None:
    service = _make_service(run_repo=None)
    result = await service.run(object())
    assert isinstance(result, ReconciliationResult)


@pytest.mark.asyncio
async def test_list_recent_runs_delegates_to_repo() -> None:
    repo = FakeRunRepository()
    service = _make_service(run_repo=repo)
    await service.run(object(), trigger="SCHEDULED")
    runs = await service.list_recent_runs(limit=5)
    assert len(runs) == 1
    assert runs[0].trigger == "SCHEDULED"


@pytest.mark.asyncio
async def test_list_discrepancies_delegates_to_repo() -> None:
    repo = FakeRunRepository()
    service = _make_service(run_repo=repo)
    filters = DiscrepancyFilter(limit=10)
    items, total = await service.list_discrepancies(filters)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_run_without_repo_returns_empty_lists() -> None:
    service = _make_service(run_repo=None)
    runs = await service.list_recent_runs()
    items, total = await service.list_discrepancies(DiscrepancyFilter())
    assert runs == []
    assert items == []
    assert total == 0
