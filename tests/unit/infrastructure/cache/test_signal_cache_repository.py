"""Unit tests for RedisSignalCacheRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.cache.signal_cache_repository import RedisSignalCacheRepository


def _make_redis(get_return=None):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=get_return)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


class TestIsDuplicate:
    @pytest.mark.asyncio
    async def test_returns_true_when_key_exists(self) -> None:
        redis = _make_redis(get_return=b"some-signal-id")
        repo = RedisSignalCacheRepository(redis)
        assert await repo.is_duplicate("signal:dedup:1234:LONG:abc") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_key_missing(self) -> None:
        redis = _make_redis(get_return=None)
        repo = RedisSignalCacheRepository(redis)
        assert await repo.is_duplicate("signal:dedup:1234:LONG:abc") is False

    @pytest.mark.asyncio
    async def test_redis_error_returns_false_fail_open(self) -> None:
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        repo = RedisSignalCacheRepository(redis)
        result = await repo.is_duplicate("signal:dedup:1234:LONG:abc")
        assert result is False


class TestSetDedup:
    @pytest.mark.asyncio
    async def test_calls_redis_set_with_ttl(self) -> None:
        redis = _make_redis()
        repo = RedisSignalCacheRepository(redis)
        await repo.set_dedup("signal:dedup:1234:LONG:abc", "signal-uuid", 1800)
        redis.set.assert_called_once_with(
            "signal:dedup:1234:LONG:abc", "signal-uuid", ex=1800
        )

    @pytest.mark.asyncio
    async def test_redis_error_does_not_raise(self) -> None:
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        repo = RedisSignalCacheRepository(redis)
        await repo.set_dedup("key", "val", 1800)  # Should not raise


class TestActiveSignal:
    @pytest.mark.asyncio
    async def test_get_active_signal_id_returns_none_when_missing(self) -> None:
        redis = _make_redis(get_return=None)
        repo = RedisSignalCacheRepository(redis)
        result = await repo.get_active_signal_id(1234)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_signal_id_decodes_bytes(self) -> None:
        redis = _make_redis(get_return=b"signal-uuid")
        repo = RedisSignalCacheRepository(redis)
        result = await repo.get_active_signal_id(1234)
        assert result == "signal-uuid"

    @pytest.mark.asyncio
    async def test_set_active_signal_calls_redis_set(self) -> None:
        redis = _make_redis()
        repo = RedisSignalCacheRepository(redis)
        await repo.set_active_signal(1234, "signal-uuid", 900)
        redis.set.assert_called_once_with("signal:active:1234", "signal-uuid", ex=900)

    @pytest.mark.asyncio
    async def test_delete_active_signal_calls_redis_delete(self) -> None:
        redis = _make_redis()
        repo = RedisSignalCacheRepository(redis)
        await repo.delete_active_signal(1234)
        redis.delete.assert_called_once_with("signal:active:1234")
