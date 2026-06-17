"""Unit tests for AuditLogService.

Verifies that all action-specific methods call repository.append with the
correct action name, entity_type, and entity_id. Errors in the repository
must NOT propagate to the caller (fire-and-forget).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, call

import pytest

from core.application.services.audit_log_service import AuditLogService
from core.domain.interfaces.i_audit_log_repository import AuditLogEntry


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.calls: list[AuditLogEntry] = []
        self.should_fail = False

    async def append(self, entry: AuditLogEntry) -> None:
        if self.should_fail:
            raise RuntimeError("DB write failed")
        self.calls.append(entry)

    async def search(self, *args, **kwargs):
        return []

    async def count(self, *args, **kwargs):
        return 0


@pytest.fixture
def repo() -> _FakeAuditRepo:
    return _FakeAuditRepo()


@pytest.fixture
def svc(repo: _FakeAuditRepo) -> AuditLogService:
    return AuditLogService(repository=repo)


@pytest.mark.asyncio
async def test_log_user_login(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    uid = uuid.uuid4()
    await svc.log_user_login(uid, "alice", "1.2.3.4")
    assert len(repo.calls) == 1
    entry = repo.calls[0]
    assert entry.action == "USER_LOGIN"
    assert entry.entity_type == "user"
    assert entry.ip_address == "1.2.3.4"


@pytest.mark.asyncio
async def test_log_signal_approved(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    uid = uuid.uuid4()
    await svc.log_signal_approved("sig-001", uid)
    assert repo.calls[0].action == "SIGNAL_APPROVED"
    assert repo.calls[0].entity_id == "sig-001"


@pytest.mark.asyncio
async def test_log_kill_switch_activated(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    await svc.log_kill_switch_activated("daily loss", "auto_ks", "daily_loss_limit")
    entry = repo.calls[0]
    assert entry.action == "KILL_SWITCH_ACTIVATED"
    assert entry.metadata["reason"] == "daily loss"
    assert entry.metadata["source"] == "daily_loss_limit"


@pytest.mark.asyncio
async def test_repository_error_does_not_propagate(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    repo.should_fail = True
    # Must not raise even though the repository throws.
    await svc.log_user_login(uuid.uuid4(), "bob", None)
    # No assertion needed — the test passes if no exception is raised.


@pytest.mark.asyncio
async def test_log_order_placed(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    await svc.log_order_placed("ord-001", "BRK-123", "NIFTY24JAN21000CE", 50)
    entry = repo.calls[0]
    assert entry.action == "ORDER_PLACED"
    assert entry.new_value["broker_order_id"] == "BRK-123"
    assert entry.new_value["quantity"] == 50


@pytest.mark.asyncio
async def test_log_risk_violation(svc: AuditLogService, repo: _FakeAuditRepo) -> None:
    await svc.log_risk_violation("sig-002", "DAILY_LOSS_LIMIT", "Daily loss exceeded")
    entry = repo.calls[0]
    assert entry.action == "RISK_VIOLATION"
    assert entry.metadata["code"] == "DAILY_LOSS_LIMIT"
