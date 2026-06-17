"""Unit tests for RedisConfig."""

from __future__ import annotations

import pytest

from core.infrastructure.config.redis_config import RedisConfig


class TestRedisConfig:
    def test_default_redis_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        config = RedisConfig()
        assert config.redis_url.startswith("redis://")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://custom-host:6380/1")
        config = RedisConfig()
        assert config.redis_url == "redis://custom-host:6380/1"

    def test_default_decode_responses_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REDIS_DECODE_RESPONSES", raising=False)
        config = RedisConfig()
        assert config.redis_decode_responses is True
