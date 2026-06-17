"""Unit tests for RedisKillSwitchRepository.

All tests use AsyncMock for the Redis client — no real Redis connection is
required.  Tests cover RC-3 (strict is_active validation), RC-4 (datetime
parse protection), no-TTL invariants, and FAIL_CLOSED behaviour on errors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.risk.kill_switch_state import KillSwitchState
from core.infrastructure.cache.kill_switch_repository import RedisKillSwitchRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(redis_client: AsyncMock) -> RedisKillSwitchRepository:
    return RedisKillSwitchRepository(redis_client=redis_client)


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _active_hash(**overrides: str) -> dict[str, str]:
    base: dict[str, str] = {
        "is_active": "true",
        "activated_at": "2026-06-14T09:00:00+00:00",
        "activated_by": "operator",
        "activation_reason": "manual activation",
        "trigger_source": "manual",
        "deactivated_at": "",
        "deactivated_by": "",
        "deactivation_note": "",
    }
    base.update(overrides)
    return base


def _inactive_hash(**overrides: str) -> dict[str, str]:
    base: dict[str, str] = {
        "is_active": "false",
        "activated_at": "2026-06-14T09:00:00+00:00",
        "activated_by": "operator",
        "activation_reason": "manual activation",
        "trigger_source": "manual",
        "deactivated_at": "2026-06-14T10:00:00+00:00",
        "deactivated_by": "admin",
        "deactivation_note": "resolved",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# get_state: state reading
# ---------------------------------------------------------------------------


class TestGetState:
    async def test_missing_key_returns_default_inactive_state(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = {}
        state = await repo.get_state()
        assert state.is_active is False
        assert state.activated_at is None
        assert state.activated_by is None
        assert state.activation_reason is None
        assert state.deactivated_at is None
        assert state.deactivated_by is None
        assert state.deactivation_note is None

    async def test_active_hash_returns_is_active_true(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash()
        state = await repo.get_state()
        assert state.is_active is True

    async def test_inactive_hash_returns_is_active_false(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _inactive_hash()
        state = await repo.get_state()
        assert state.is_active is False

    async def test_parses_activated_at_as_datetime(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(
            activated_at="2026-06-14T09:00:00+00:00"
        )
        state = await repo.get_state()
        assert isinstance(state.activated_at, datetime)
        assert state.activated_at == datetime(2026, 6, 14, 9, 0, 0, tzinfo=UTC)

    async def test_empty_string_optional_fields_return_none(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(
            activated_at="",
            activated_by="",
            activation_reason="",
        )
        state = await repo.get_state()
        assert state.activated_at is None
        assert state.activated_by is None
        assert state.activation_reason is None

    async def test_uses_hgetall_not_get(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = {}
        await repo.get_state()
        redis_client.hgetall.assert_called_once_with("system:kill_switch")
        redis_client.get.assert_not_called()

    async def test_returns_kill_switch_state_instance(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash()
        state = await repo.get_state()
        assert isinstance(state, KillSwitchState)

    async def test_connection_error_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.side_effect = RedisConnectionError("connection refused")
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_state()

    async def test_error_source_is_kill_switch(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.side_effect = RedisConnectionError("connection refused")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_state()
        assert exc_info.value.source == "kill_switch"

    async def test_timeout_error_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.side_effect = RedisTimeoutError("operation timed out")
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_state()


# ---------------------------------------------------------------------------
# RC-3: strict is_active validation (FAIL_CLOSED)
# ---------------------------------------------------------------------------


class TestRC3IsActiveValidation:
    async def test_capital_T_fails_closed(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(is_active="True")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_state()
        assert exc_info.value.source == "kill_switch"

    async def test_numeric_one_fails_closed(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(is_active="1")
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_state()

    async def test_yes_fails_closed(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(is_active="yes")
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_state()

    async def test_all_caps_TRUE_fails_closed(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(is_active="TRUE")
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_state()

    async def test_missing_is_active_in_present_hash_fails_closed(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = {
            "activated_by": "operator",
            "activation_reason": "manual",
        }
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_state()
        assert exc_info.value.source == "kill_switch"


# ---------------------------------------------------------------------------
# RC-4: datetime parse protection
# ---------------------------------------------------------------------------


class TestRC4DatetimeParsing:
    async def test_malformed_activated_at_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _active_hash(activated_at="CORRUPTED")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_state()
        assert exc_info.value.source == "kill_switch"

    async def test_malformed_deactivated_at_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hgetall.return_value = _inactive_hash(deactivated_at="not-a-date")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_state()
        assert exc_info.value.source == "kill_switch"


# ---------------------------------------------------------------------------
# activate
# ---------------------------------------------------------------------------


class TestActivate:
    async def test_activate_sets_is_active_string_true(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["is_active"] == "true"

    async def test_activate_records_activated_by(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="risk_engine", trigger_source="daily_loss")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["activated_by"] == "risk_engine"

    async def test_activate_records_activation_reason(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(
            reason="daily loss limit exceeded",
            activated_by="risk_engine",
            trigger_source="daily_loss_100pct",
        )
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["activation_reason"] == "daily loss limit exceeded"

    async def test_activate_records_activated_at_iso8601(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        parsed = datetime.fromisoformat(mapping["activated_at"])
        assert isinstance(parsed, datetime)

    async def test_activate_stores_trigger_source(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(
            reason="test", activated_by="operator", trigger_source="daily_loss_100pct"
        )
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["trigger_source"] == "daily_loss_100pct"

    async def test_activate_uses_hset_not_set(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        redis_client.hset.assert_called_once()
        redis_client.set.assert_not_called()

    async def test_activate_never_calls_expire(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        redis_client.expire.assert_not_called()

    async def test_activate_never_calls_pexpire(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        redis_client.pexpire.assert_not_called()

    async def test_activate_connection_error_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hset.side_effect = RedisConnectionError("connection refused")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.activate(reason="test", activated_by="operator", trigger_source="manual")
        assert exc_info.value.source == "kill_switch"


# ---------------------------------------------------------------------------
# deactivate
# ---------------------------------------------------------------------------


class TestDeactivate:
    async def test_deactivate_sets_is_active_string_false(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.deactivate(deactivated_by="admin", note="resolved")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["is_active"] == "false"

    async def test_deactivate_records_deactivated_by(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.deactivate(deactivated_by="admin_user", note="resolved")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["deactivated_by"] == "admin_user"

    async def test_deactivate_records_deactivation_note(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.deactivate(deactivated_by="admin", note="market closed cleanly")
        mapping = redis_client.hset.call_args.kwargs["mapping"]
        assert mapping["deactivation_note"] == "market closed cleanly"

    async def test_deactivate_never_calls_expire(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        await repo.deactivate(deactivated_by="admin", note="resolved")
        redis_client.expire.assert_not_called()
        redis_client.pexpire.assert_not_called()

    async def test_deactivate_connection_error_raises_data_source_unavailable(
        self, repo: RedisKillSwitchRepository, redis_client: AsyncMock
    ) -> None:
        redis_client.hset.side_effect = RedisConnectionError("connection refused")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.deactivate(deactivated_by="admin", note="resolved")
        assert exc_info.value.source == "kill_switch"
