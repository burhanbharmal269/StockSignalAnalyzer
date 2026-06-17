"""Unit tests for LoginRateLimiter (Redis-backed brute-force protection)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.auth.rate_limiter import LoginRateLimiter


def _make_redis() -> MagicMock:
    r = MagicMock()
    r.exists = AsyncMock(return_value=0)
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock()
    r.setex = AsyncMock()
    r.delete = AsyncMock()
    return r


@pytest.fixture()
def redis() -> MagicMock:
    return _make_redis()


@pytest.fixture()
def limiter(redis: MagicMock) -> LoginRateLimiter:
    return LoginRateLimiter(
        redis_client=redis,
        max_attempts=5,
        attempt_window_seconds=600,
        lockout_seconds=1800,
    )


class TestHashedIp:
    def test_same_ip_same_hash(self, limiter: LoginRateLimiter) -> None:
        assert limiter._hashed_ip("1.2.3.4") == limiter._hashed_ip("1.2.3.4")

    def test_different_ips_different_hashes(self, limiter: LoginRateLimiter) -> None:
        assert limiter._hashed_ip("1.2.3.4") != limiter._hashed_ip("5.6.7.8")

    def test_hash_is_16_chars(self, limiter: LoginRateLimiter) -> None:
        assert len(limiter._hashed_ip("1.2.3.4")) == 16


class TestIsLockedOut:
    async def test_not_locked_when_key_absent(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=0)
        assert await limiter.is_locked_out("1.2.3.4") is False

    async def test_locked_when_key_present(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=1)
        assert await limiter.is_locked_out("1.2.3.4") is True

    async def test_uses_lockout_prefix(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=0)
        await limiter.is_locked_out("1.2.3.4")
        call_key = redis.exists.call_args[0][0]
        assert call_key.startswith("auth:lockout:")


class TestRecordFailure:
    async def test_returns_current_count(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=3)
        count = await limiter.record_failure("1.2.3.4")
        assert count == 3

    async def test_sets_expire_on_first_failure(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=1)
        await limiter.record_failure("1.2.3.4")
        redis.expire.assert_awaited_once()

    async def test_no_expire_on_second_failure(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=2)
        await limiter.record_failure("1.2.3.4")
        redis.expire.assert_not_awaited()

    async def test_lockout_set_at_threshold(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=5)
        await limiter.record_failure("1.2.3.4")
        redis.setex.assert_awaited_once()
        call_key = redis.setex.call_args[0][0]
        assert call_key.startswith("auth:lockout:")

    async def test_lockout_set_above_threshold(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=10)
        await limiter.record_failure("1.2.3.4")
        redis.setex.assert_awaited_once()

    async def test_no_lockout_below_threshold(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        redis.incr = AsyncMock(return_value=4)
        await limiter.record_failure("1.2.3.4")
        redis.setex.assert_not_awaited()


class TestRecordSuccess:
    async def test_deletes_both_keys(
        self, limiter: LoginRateLimiter, redis: MagicMock
    ) -> None:
        await limiter.record_success("1.2.3.4")
        redis.delete.assert_awaited_once()
        deleted_keys = redis.delete.call_args[0]
        assert any("auth:attempts:" in k for k in deleted_keys)
        assert any("auth:lockout:" in k for k in deleted_keys)
