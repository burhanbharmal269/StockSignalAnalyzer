"""Unit tests for RedisAccountStateRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.infrastructure.cache.account_state_repository import RedisAccountStateRepository

_VALID_HASH = {
    "account_capital": "500000",
    "session_capital": "500000",
    "available_margin": "400000",
    "used_margin": "100000",
    "margin_utilization_pct": "20.0",
    "daily_pnl": "-500",
    "daily_loss_consumed_pct": "5.0",
    "weekly_pnl": "-1000",
    "weekly_loss_consumed_pct": "4.0",
    "drawdown_from_hwm_pct": "1.0",
    "open_positions_count": "2",
    "position_size_multiplier": "1.0",
    "trading_mode": "LIVE",
    "captured_at": "2026-06-14T09:30:00+00:00",
}


@pytest.fixture
def redis_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(redis_mock: AsyncMock) -> RedisAccountStateRepository:
    return RedisAccountStateRepository(redis_client=redis_mock)


class TestGetCurrentSuccess:
    async def test_returns_account_state(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.account_capital == Decimal("500000")

    async def test_session_capital_parsed(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.session_capital == Decimal("500000")

    async def test_available_margin_parsed(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.available_margin == Decimal("400000")

    async def test_daily_pnl_parsed_negative(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.daily_pnl == Decimal("-500")

    async def test_open_positions_count_int(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.open_positions_count == 2

    async def test_position_size_multiplier_float(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.position_size_multiplier == 1.0

    async def test_trading_mode_live(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.trading_mode == "LIVE"

    async def test_captured_at_parsed(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_HASH
        state = await repo.get_current()
        assert state.captured_at.year == 2026


class TestGetCurrentFailures:
    async def test_empty_hash_raises(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {}
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_current()
        assert exc_info.value.source == "account_state"

    async def test_missing_field_raises(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        partial = {k: v for k, v in _VALID_HASH.items() if k != "daily_pnl"}
        redis_mock.hgetall.return_value = partial
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_current()

    async def test_invalid_decimal_raises(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        bad = dict(_VALID_HASH)
        bad["account_capital"] = "not_a_number"
        redis_mock.hgetall.return_value = bad
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_current()

    async def test_invalid_int_raises(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        bad = dict(_VALID_HASH)
        bad["open_positions_count"] = "two"
        redis_mock.hgetall.return_value = bad
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_current()

    async def test_redis_connection_error_raises(self, repo: RedisAccountStateRepository, redis_mock: AsyncMock) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError
        redis_mock.hgetall.side_effect = RedisConnectionError("conn lost")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_current()
        assert exc_info.value.source == "account_state"
