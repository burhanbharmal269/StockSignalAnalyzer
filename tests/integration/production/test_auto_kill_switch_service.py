"""Unit tests for AutoKillSwitchService.

Tests that each trigger condition correctly activates the kill switch,
and that no activation occurs when all checks pass.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.auto_kill_switch_service import (
    AutoKillSwitchService,
    _BROKER_UNAVAILABLE_THRESHOLD_SECONDS,
    _CONSECUTIVE_FAILURE_THRESHOLD,
)


class _FakeKillSwitchState:
    def __init__(self, is_active: bool = False) -> None:
        self.is_active = is_active


class _FakeKsRepo:
    def __init__(self) -> None:
        self._active = False

    async def get_state(self) -> _FakeKillSwitchState:
        return _FakeKillSwitchState(is_active=self._active)


class _FakeKsService:
    def __init__(self) -> None:
        self.activated_with: list[dict] = []

    async def activate(self, reason: str, activated_by: str, trigger_source: str) -> None:
        self.activated_with.append(
            {"reason": reason, "activated_by": activated_by, "source": trigger_source}
        )


def _make_broker_health(status: str = "HEALTHY") -> MagicMock:
    service = AsyncMock()
    report = MagicMock()
    report.status.value = status
    service.check.return_value = report
    return service


def _make_broker_execution(consecutive_failures: int = 0) -> MagicMock:
    svc = MagicMock()
    svc.consecutive_failures = consecutive_failures
    return svc


def _make_account_state_repo(daily_pnl: float = 0.0) -> AsyncMock:
    repo = AsyncMock()
    state = MagicMock()
    state.daily_pnl = daily_pnl
    repo.get_current.return_value = state
    repo.get.return_value = state
    return repo


def _make_redis(ping_ok: bool = True) -> AsyncMock:
    redis = AsyncMock()
    if not ping_ok:
        redis.ping.side_effect = ConnectionError("Redis down")
    return redis


def _make_risk_config(total_capital: int = 500_000, daily_loss_abs: int = 10_000, daily_loss_pct: float = 2.0) -> MagicMock:
    cfg = MagicMock()
    cfg.capital.total_capital = total_capital
    cfg.daily_loss.limit_abs = daily_loss_abs
    cfg.daily_loss.limit_pct = daily_loss_pct
    return cfg


def _build_service(
    ks_repo=None,
    ks_service=None,
    broker_health=None,
    broker_execution=None,
    account_repo=None,
    redis=None,
    risk_config=None,
) -> tuple[AutoKillSwitchService, _FakeKsRepo, _FakeKsService]:
    _ks_repo = ks_repo or _FakeKsRepo()
    _ks_service = ks_service or _FakeKsService()
    svc = AutoKillSwitchService(
        kill_switch_service=_ks_service,
        kill_switch_repository=_ks_repo,
        broker_health_service=broker_health or _make_broker_health("HEALTHY"),
        broker_execution_service=broker_execution or _make_broker_execution(0),
        account_state_repository=account_repo or _make_account_state_repo(0.0),
        redis_client=redis or _make_redis(True),
        risk_config=risk_config or _make_risk_config(),
    )
    return svc, _ks_repo, _ks_service


@pytest.mark.asyncio
async def test_no_activation_when_all_healthy() -> None:
    svc, _, ks_svc = _build_service()
    await svc._check_all()
    assert len(ks_svc.activated_with) == 0


@pytest.mark.asyncio
async def test_consecutive_failures_trigger() -> None:
    svc, _, ks_svc = _build_service(
        broker_execution=_make_broker_execution(_CONSECUTIVE_FAILURE_THRESHOLD)
    )
    await svc._check_all()
    assert len(ks_svc.activated_with) == 1
    assert ks_svc.activated_with[0]["source"] == "consecutive_failures"


@pytest.mark.asyncio
async def test_redis_disconnect_trigger() -> None:
    svc, _, ks_svc = _build_service(redis=_make_redis(ping_ok=False))
    await svc._check_all()
    assert len(ks_svc.activated_with) == 1
    assert ks_svc.activated_with[0]["source"] == "redis_disconnect"


@pytest.mark.asyncio
async def test_no_double_activation_when_already_active() -> None:
    ks_repo = _FakeKsRepo()
    ks_repo._active = True
    svc, _, ks_svc = _build_service(
        ks_repo=ks_repo,
        redis=_make_redis(ping_ok=False),  # would trigger if not already active
    )
    await svc._check_all()
    assert len(ks_svc.activated_with) == 0


@pytest.mark.asyncio
async def test_daily_pnl_breach_triggers() -> None:
    # Daily PnL loss exceeds both pct and abs limits
    risk_cfg = _make_risk_config(total_capital=500_000, daily_loss_abs=10_000, daily_loss_pct=2.0)
    account = _make_account_state_repo(daily_pnl=-11_000.0)
    svc, _, ks_svc = _build_service(account_repo=account, risk_config=risk_cfg)
    await svc._check_all()
    assert len(ks_svc.activated_with) == 1
    assert ks_svc.activated_with[0]["source"] == "daily_loss_limit"
