"""Unit tests for RedisPortfolioStateRepository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.risk.graduated_response_state import GraduatedResponseState
from core.infrastructure.cache.portfolio_state_repository import RedisPortfolioStateRepository

_VALID_PORT_HASH = {
    "open_positions_count": "3",
    "positions_per_underlying": json.dumps({"NIFTY": 2, "BANKNIFTY": 1}),
    "capital_per_underlying_pct": json.dumps({"NIFTY": 10.0, "BANKNIFTY": 5.0}),
    "net_delta": "250.5",
    "net_vega": "12500.0",
    "net_theta_daily": "-500.0",
    "orders_last_minute": "1",
    "orders_today": "5",
    "captured_at": "2026-06-14T09:30:00+00:00",
}

_VALID_GRAD_HASH = {
    "state": "NORMAL",
    "position_size_multiplier": "1.0",
    "activated_at": "",
    "reason": "",
}


@pytest.fixture
def redis_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(redis_mock: AsyncMock) -> RedisPortfolioStateRepository:
    return RedisPortfolioStateRepository(redis_client=redis_mock)


class TestGetCurrentPortfolioState:
    async def test_parses_open_positions_count(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_PORT_HASH
        state = await repo.get_current()
        assert state.open_positions_count == 3

    async def test_parses_positions_per_underlying(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_PORT_HASH
        state = await repo.get_current()
        assert state.positions_per_underlying == {"NIFTY": 2, "BANKNIFTY": 1}

    async def test_parses_net_delta(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_PORT_HASH
        state = await repo.get_current()
        assert state.net_delta == pytest.approx(250.5)

    async def test_empty_hash_raises(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {}
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_current()
        assert exc_info.value.source == "portfolio_state"

    async def test_invalid_json_raises(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        bad = dict(_VALID_PORT_HASH)
        bad["positions_per_underlying"] = "{broken json"
        redis_mock.hgetall.return_value = bad
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_current()


class TestGetGraduatedResponse:
    async def test_normal_state(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = _VALID_GRAD_HASH
        grad = await repo.get_graduated_response()
        assert grad.state == "NORMAL"
        assert grad.position_size_multiplier == 1.0

    async def test_reduced_state(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {
            "state": "REDUCED",
            "position_size_multiplier": "0.5",
            "activated_at": "2026-06-14T10:00:00+00:00",
            "reason": "daily loss 50%",
        }
        grad = await repo.get_graduated_response()
        assert grad.state == "REDUCED"
        assert grad.position_size_multiplier == 0.5

    async def test_empty_hash_returns_normal_default(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {}
        grad = await repo.get_graduated_response()
        assert grad.state == "NORMAL"

    async def test_invalid_state_raises(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {"state": "UNKNOWN"}
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_graduated_response()

    async def test_missing_state_field_raises(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        redis_mock.hgetall.return_value = {"other_field": "value"}
        with pytest.raises(DataSourceUnavailableError):
            await repo.get_graduated_response()


class TestSetGraduatedResponse:
    async def test_writes_state_to_redis(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        state = GraduatedResponseState(
            state="REDUCED",
            position_size_multiplier=0.5,
            activated_at=datetime(2026, 6, 14, 10, 0, 0, tzinfo=UTC),
            reason="loss limit",
        )
        redis_mock.hset.return_value = 4
        await repo.set_graduated_response(state)
        redis_mock.hset.assert_called_once()
        call_kwargs = redis_mock.hset.call_args
        mapping = call_kwargs[1]["mapping"]
        assert mapping["state"] == "REDUCED"
        assert mapping["position_size_multiplier"] == "0.5"

    async def test_none_reason_writes_empty_string(self, repo: RedisPortfolioStateRepository, redis_mock: AsyncMock) -> None:
        state = GraduatedResponseState(
            state="NORMAL",
            position_size_multiplier=1.0,
            activated_at=None,
            reason=None,
        )
        redis_mock.hset.return_value = 4
        await repo.set_graduated_response(state)
        mapping = redis_mock.hset.call_args[1]["mapping"]
        assert mapping["reason"] == ""
        assert mapping["activated_at"] == ""
