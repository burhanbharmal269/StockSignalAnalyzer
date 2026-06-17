"""Unit tests for DatabaseConfig."""

from __future__ import annotations

import pytest

from core.infrastructure.config.database_config import DatabaseConfig


class TestDatabaseConfig:
    def test_default_write_url_is_asyncpg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_WRITE_URL", raising=False)
        config = DatabaseConfig()
        assert "asyncpg" in config.database_write_url

    def test_effective_read_url_falls_back_to_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_WRITE_URL", "postgresql+asyncpg://primary/db")
        monkeypatch.setenv("DATABASE_READ_URL", "")
        config = DatabaseConfig()
        assert config.effective_read_url == "postgresql+asyncpg://primary/db"

    def test_effective_read_url_uses_replica_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_WRITE_URL", "postgresql+asyncpg://primary/db")
        monkeypatch.setenv("DATABASE_READ_URL", "postgresql+asyncpg://replica/db")
        config = DatabaseConfig()
        assert config.effective_read_url == "postgresql+asyncpg://replica/db"

    def test_pool_size_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_POOL_SIZE", "5")
        config = DatabaseConfig()
        assert config.database_pool_size == 5
