"""Unit tests for BrokerRetryService.

Tests the exponential backoff schedule, error classification, and kill switch
fail-closed behaviour.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.services.broker.broker_retry_service import (
    BrokerRetryService,
    KillSwitchActiveError,
    _MAX_ATTEMPTS,
    _RETRY_DELAYS_SECONDS,
)
from core.domain.exceptions.broker import BrokerConnectionError, BrokerOrderError
from core.domain.risk.kill_switch_state import KillSwitchState


class _FakeKillSwitchRepository:
    def __init__(self, is_active: bool = False) -> None:
        self._is_active = is_active
        self._state = MagicMock()
        self._state.is_active = is_active

    async def get_state(self) -> MagicMock:
        return self._state


@pytest.fixture
def ks_repo_inactive() -> _FakeKillSwitchRepository:
    return _FakeKillSwitchRepository(is_active=False)


@pytest.fixture
def ks_repo_active() -> _FakeKillSwitchRepository:
    return _FakeKillSwitchRepository(is_active=True)


@pytest.mark.asyncio
async def test_success_on_first_attempt(ks_repo_inactive) -> None:
    svc = BrokerRetryService(kill_switch_repository=ks_repo_inactive)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        return "broker-order-001"

    result = await svc.execute_with_retry(operation, "test_op")

    assert result.success is True
    assert result.value == "broker-order-001"
    assert len(result.attempts) == 1
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_on_connection_error(ks_repo_inactive) -> None:
    svc = BrokerRetryService(kill_switch_repository=ks_repo_inactive)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise BrokerConnectionError("timeout")
        return "order-999"

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await svc.execute_with_retry(operation, "test_connection_retry")

    assert result.success is True
    assert call_count == 3
    assert len(result.attempts) == 3


@pytest.mark.asyncio
async def test_non_retryable_error_stops_immediately(ks_repo_inactive) -> None:
    svc = BrokerRetryService(kill_switch_repository=ks_repo_inactive)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        raise BrokerOrderError(
            message="Insufficient margin", code="MARGIN_INSUFFICIENT", broker_name="test"
        )

    result = await svc.execute_with_retry(operation, "test_non_retryable")

    assert result.success is False
    assert call_count == 1  # must NOT retry
    assert len(result.attempts) == 1


@pytest.mark.asyncio
async def test_exhausts_all_retries(ks_repo_inactive) -> None:
    svc = BrokerRetryService(kill_switch_repository=ks_repo_inactive)
    call_count = 0

    async def operation():
        nonlocal call_count
        call_count += 1
        raise BrokerConnectionError("always fails")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await svc.execute_with_retry(operation, "test_exhausted")

    assert result.success is False
    assert call_count == _MAX_ATTEMPTS
    assert result.final_error is not None


@pytest.mark.asyncio
async def test_kill_switch_active_aborts_before_attempt(ks_repo_active) -> None:
    svc = BrokerRetryService(kill_switch_repository=ks_repo_active)
    called = False

    async def operation():
        nonlocal called
        called = True
        return "should-not-reach"

    result = await svc.execute_with_retry(operation, "test_ks_active")

    assert result.success is False
    assert called is False  # Kill switch prevents any attempt
    assert "Kill switch" in (result.final_error or "")
