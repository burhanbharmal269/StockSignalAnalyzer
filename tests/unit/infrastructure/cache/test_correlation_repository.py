"""Unit tests for RedisCorrelationRepository."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from core.infrastructure.cache.correlation_repository import RedisCorrelationRepository


@pytest.fixture
def redis_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(redis_mock: AsyncMock) -> RedisCorrelationRepository:
    return RedisCorrelationRepository(redis_client=redis_mock)


class TestGetMatrix:
    async def test_returns_parsed_matrix(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        matrix = {"NIFTY": {"BANKNIFTY": 0.85}, "BANKNIFTY": {"NIFTY": 0.85}}
        redis_mock.get.return_value = json.dumps(matrix)
        result = await repo.get_matrix()
        assert result == matrix

    async def test_cache_miss_returns_empty_dict(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = None
        result = await repo.get_matrix()
        assert result == {}

    async def test_redis_error_returns_empty_dict(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError
        redis_mock.get.side_effect = RedisConnectionError("down")
        result = await repo.get_matrix()
        assert result == {}

    async def test_malformed_json_returns_empty_dict(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "{broken json"
        result = await repo.get_matrix()
        assert result == {}

    async def test_returns_empty_dict_on_type_error(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "null"
        result = await repo.get_matrix()
        assert result == {}

    async def test_nested_correlation_values(self, repo: RedisCorrelationRepository, redis_mock: AsyncMock) -> None:
        matrix = {
            "NIFTY": {"BANKNIFTY": 0.85, "FINNIFTY": 0.75},
            "BANKNIFTY": {"NIFTY": 0.85},
        }
        redis_mock.get.return_value = json.dumps(matrix)
        result = await repo.get_matrix()
        assert result["NIFTY"]["FINNIFTY"] == pytest.approx(0.75)
