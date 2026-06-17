"""Unit tests for SignalDedupService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.application.services.signal_dedup_service import SignalDedupService
from core.infrastructure.config.confidence_config import load_confidence_config

_cfg = load_confidence_config()

_TOKEN = 256265
_DIR = "LONG"
_BUCKET = "STANDARD"
_SCORE = 75.0


def _make_service(redis: AsyncMock | None = None) -> SignalDedupService:
    if redis is None:
        redis = AsyncMock()
        redis.get.return_value = None
    return SignalDedupService(redis_client=redis, config=_cfg)


class TestSignalDedupService:
    @pytest.mark.asyncio
    async def test_first_signal_not_duplicate(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = None
        svc = _make_service(redis)
        assert await svc.is_duplicate(_TOKEN, _DIR, _BUCKET, _SCORE) is False

    @pytest.mark.asyncio
    async def test_second_signal_within_ttl_same_score_is_duplicate(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = str(_SCORE)
        svc = _make_service(redis)
        assert await svc.is_duplicate(_TOKEN, _DIR, _BUCKET, _SCORE) is True

    @pytest.mark.asyncio
    async def test_large_score_delta_not_duplicate(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = str(_SCORE)
        svc = _make_service(redis)
        new_score = _SCORE + _cfg.dedup.score_delta_threshold + 1.0
        assert await svc.is_duplicate(_TOKEN, _DIR, _BUCKET, new_score) is False

    @pytest.mark.asyncio
    async def test_register_calls_setex_with_ttl(self) -> None:
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.register(_TOKEN, _DIR, _BUCKET, _SCORE)
        redis.setex.assert_called_once()
        call_args = redis.setex.call_args[0]
        assert call_args[1] == _cfg.dedup.ttl_seconds

    @pytest.mark.asyncio
    async def test_key_includes_instrument_token_direction_bucket(self) -> None:
        redis = AsyncMock()
        svc = _make_service(redis)
        await svc.register(_TOKEN, _DIR, _BUCKET, _SCORE)
        key = redis.setex.call_args[0][0]
        assert str(_TOKEN) in key
        assert _DIR in key
        assert _BUCKET in key

    @pytest.mark.asyncio
    async def test_different_direction_uses_different_key(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = str(_SCORE)
        svc = _make_service(redis)
        redis.get.return_value = None  # no key for SHORT
        assert await svc.is_duplicate(_TOKEN, "SHORT", _BUCKET, _SCORE) is False

    @pytest.mark.asyncio
    async def test_score_delta_at_threshold_is_duplicate(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = str(_SCORE)
        svc = _make_service(redis)
        delta_score = _SCORE + _cfg.dedup.score_delta_threshold
        assert await svc.is_duplicate(_TOKEN, _DIR, _BUCKET, delta_score) is True

    @pytest.mark.asyncio
    async def test_corrupted_redis_value_not_duplicate(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = "not_a_float"
        svc = _make_service(redis)
        assert await svc.is_duplicate(_TOKEN, _DIR, _BUCKET, _SCORE) is False
