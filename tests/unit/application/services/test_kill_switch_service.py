"""Unit tests for KillSwitchService — idempotency and activation order (AD-D-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, call

import pytest

from core.application.services.kill_switch_service import KillSwitchService
from core.domain.events.risk_events import KillSwitchActivated, KillSwitchDeactivated
from core.domain.exceptions.risk import RiskDecisionPersistenceError
from core.domain.risk.kill_switch_state import KillSwitchState


def _inactive_state() -> KillSwitchState:
    return KillSwitchState(
        is_active=False,
        activated_at=None,
        activated_by=None,
        activation_reason=None,
        deactivated_at=None,
        deactivated_by=None,
        deactivation_note=None,
    )


def _active_state() -> KillSwitchState:
    return KillSwitchState(
        is_active=True,
        activated_at=datetime(2026, 6, 14, 9, 0, 0, tzinfo=UTC),
        activated_by="risk_engine",
        activation_reason="daily loss",
        deactivated_at=None,
        deactivated_by=None,
        deactivation_note=None,
    )


@pytest.fixture
def ks_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ks_events_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def event_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock) -> KillSwitchService:
    return KillSwitchService(
        kill_switch_repo=ks_repo,
        kill_switch_events_repo=ks_events_repo,
        event_bus=event_bus,
    )


class TestStartupCheck:
    async def test_inactive_state_logs_info(
        self, service: KillSwitchService, ks_repo: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _inactive_state()
        await service.startup_check()
        ks_repo.get_state.assert_called_once()

    async def test_active_state_does_not_raise(
        self, service: KillSwitchService, ks_repo: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _active_state()
        await service.startup_check()  # should not raise


class TestActivate:
    async def test_when_inactive_calls_repo_activate(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _inactive_state()
        await service.activate("loss limit", "risk_engine", "daily_loss_100pct")
        ks_repo.activate.assert_called_once_with(
            reason="loss limit",
            activated_by="risk_engine",
            trigger_source="daily_loss_100pct",
        )

    async def test_activation_order_redis_then_db_then_event(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        call_order: list[str] = []
        ks_repo.get_state.return_value = _inactive_state()

        async def track_activate(**_: object) -> None:
            call_order.append("redis")

        async def track_insert(**_: object) -> None:
            call_order.append("db")

        async def track_publish(_: object) -> None:
            call_order.append("event")

        ks_repo.activate.side_effect = track_activate
        ks_events_repo.insert_event.side_effect = track_insert
        event_bus.publish.side_effect = track_publish

        await service.activate("loss limit", "risk_engine", "daily_loss_100pct")
        assert call_order == ["redis", "db", "event"]

    async def test_idempotent_when_already_active(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _active_state()
        await service.activate("second reason", "risk_engine", "drawdown")
        ks_repo.activate.assert_not_called()
        ks_events_repo.insert_event.assert_not_called()
        event_bus.publish.assert_not_called()

    async def test_db_insert_failure_no_event_published(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _inactive_state()
        ks_events_repo.insert_event.side_effect = RiskDecisionPersistenceError("db error")
        await service.activate("loss limit", "risk_engine", "daily_loss_100pct")
        event_bus.publish.assert_not_called()

    async def test_publishes_kill_switch_activated_event(
        self, service: KillSwitchService, ks_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _inactive_state()
        await service.activate("loss limit", "risk_engine", "daily_loss_100pct")
        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, KillSwitchActivated)
        assert event.reason == "loss limit"
        assert event.activated_by == "risk_engine"


class TestDeactivate:
    async def test_when_active_calls_repo_deactivate(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _active_state()
        await service.deactivate("admin", "manual override")
        ks_repo.deactivate.assert_called_once_with(
            deactivated_by="admin",
            note="manual override",
            override_loss_check=False,
        )

    async def test_idempotent_when_already_inactive(
        self, service: KillSwitchService, ks_repo: AsyncMock, ks_events_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _inactive_state()
        await service.deactivate("admin", "note")
        ks_repo.deactivate.assert_not_called()
        event_bus.publish.assert_not_called()

    async def test_publishes_kill_switch_deactivated_event(
        self, service: KillSwitchService, ks_repo: AsyncMock, event_bus: AsyncMock
    ) -> None:
        ks_repo.get_state.return_value = _active_state()
        await service.deactivate("admin", "recovery confirmed")
        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, KillSwitchDeactivated)
        assert event.deactivated_by == "admin"
