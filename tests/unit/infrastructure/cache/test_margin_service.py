"""Unit tests for RedisMarginService."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from core.domain.exceptions.risk import MarginDataUnavailableError
from core.infrastructure.cache.margin_service import RedisMarginService


def _make_config(timeout_ms: int = 150) -> object:
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.margin.timeout_ms = timeout_ms
    cfg.margin.timeout_seconds = timeout_ms / 1000.0
    return cfg


@pytest.fixture
def redis_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def repo(redis_mock: AsyncMock) -> RedisMarginService:
    return RedisMarginService(redis_client=redis_mock, config=_make_config())


class TestGetRequiredMargin:
    async def test_returns_margin_times_lots(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "50000"
        result = await repo.get_required_margin(12345, 2, 0.15)
        assert result == Decimal("100000")

    async def test_single_lot(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "75000"
        result = await repo.get_required_margin(99, 1, 0.15)
        assert result == Decimal("75000")

    async def test_cache_miss_raises(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = None
        with pytest.raises(MarginDataUnavailableError) as exc_info:
            await repo.get_required_margin(12345, 1, 0.15)
        assert exc_info.value.source == "margin_cache"
        assert "instrument_token=12345" in str(exc_info.value)

    async def test_invalid_decimal_raises(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "not_a_number"
        with pytest.raises(MarginDataUnavailableError):
            await repo.get_required_margin(12345, 1, 0.15)

    async def test_redis_error_raises(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError
        redis_mock.get.side_effect = RedisConnectionError("conn lost")
        with pytest.raises(MarginDataUnavailableError) as exc_info:
            await repo.get_required_margin(12345, 1, 0.15)
        assert exc_info.value.source == "margin_cache"

    async def test_timeout_raises(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        async def slow_get(key: str) -> None:
            await asyncio.sleep(10)

        redis_mock.get.side_effect = slow_get
        cfg = _make_config(timeout_ms=1)
        fast_repo = RedisMarginService(redis_client=redis_mock, config=cfg)
        with pytest.raises(MarginDataUnavailableError) as exc_info:
            await fast_repo.get_required_margin(12345, 1, 0.001)
        assert "timeout" in str(exc_info.value).lower()

    async def test_uses_config_timeout(self, repo: RedisMarginService, redis_mock: AsyncMock) -> None:
        redis_mock.get.return_value = "50000"
        with patch("core.infrastructure.cache.margin_service.asyncio.wait_for") as mock_wait:
            async def fake_wait_for(coro: object, timeout: float) -> str:
                assert timeout == pytest.approx(0.15)
                if asyncio.iscoroutine(coro):
                    return await coro
                return coro  # type: ignore[return-value]

            mock_wait.side_effect = fake_wait_for
            await repo.get_required_margin(12345, 1, 0.15)
