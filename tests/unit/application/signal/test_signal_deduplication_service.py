"""Unit tests for SignalDeduplicationService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.application.services.signal.signal_deduplication_service import (
    SignalDeduplicationService,
)
from core.infrastructure.config.signal_config import SignalConfig


def _make_cache(is_dup: bool = False) -> AsyncMock:
    cache = AsyncMock()
    cache.is_duplicate = AsyncMock(return_value=is_dup)
    cache.set_dedup = AsyncMock()
    return cache


def _config() -> SignalConfig:
    return SignalConfig()


class TestIsDuplicate:
    @pytest.mark.asyncio
    async def test_returns_true_when_cache_says_duplicate(self) -> None:
        service = SignalDeduplicationService(_make_cache(is_dup=True), _config())
        result = await service.is_duplicate(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_duplicate(self) -> None:
        service = SignalDeduplicationService(_make_cache(is_dup=False), _config())
        result = await service.is_duplicate(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "abc")
        assert result is False

    @pytest.mark.asyncio
    async def test_passes_correct_key_to_cache(self) -> None:
        cache = _make_cache()
        cfg = _config()
        service = SignalDeduplicationService(cache, cfg)
        await service.is_duplicate(1234, "SHORT", "MEAN_REVERSION", "SIDEWAYS", "sha256hex")
        expected_key = cfg.dedup_key(1234, "SHORT", "MEAN_REVERSION", "SIDEWAYS", "sha256hex")
        cache.is_duplicate.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_different_strategies_produce_different_keys(self) -> None:
        cfg = _config()
        trend_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "sha")
        mr_key = cfg.dedup_key(1234, "LONG", "MEAN_REVERSION", "TRENDING_BULLISH", "sha")
        assert trend_key != mr_key

    @pytest.mark.asyncio
    async def test_different_regimes_produce_different_keys(self) -> None:
        cfg = _config()
        bull_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "sha")
        bear_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BEARISH", "sha")
        assert bull_key != bear_key

    @pytest.mark.asyncio
    async def test_different_directions_produce_different_keys(self) -> None:
        cfg = _config()
        long_key = cfg.dedup_key(1234, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "sha")
        short_key = cfg.dedup_key(1234, "SHORT", "DIRECTIONAL", "TRENDING_BULLISH", "sha")
        assert long_key != short_key


class TestRegister:
    @pytest.mark.asyncio
    async def test_calls_set_dedup_with_correct_args(self) -> None:
        cache = _make_cache()
        cfg = _config()
        service = SignalDeduplicationService(cache, cfg)
        await service.register(9999, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "abcdef", "sig-uuid")
        expected_key = cfg.dedup_key(9999, "LONG", "DIRECTIONAL", "TRENDING_BULLISH", "abcdef")
        cache.set_dedup.assert_called_once_with(
            expected_key, "sig-uuid", cfg.dedup_ttl_seconds
        )
