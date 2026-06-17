"""Database connection configuration loaded from environment variables.

DATABASE_WRITE_URL  — primary PostgreSQL URL (required)
DATABASE_READ_URL   — read replica URL (defaults to write URL)
DATABASE_POOL_SIZE  — default 10
DATABASE_MAX_OVERFLOW — default 20
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_write_url: str = Field(
        default="postgresql+asyncpg://trading:trading@localhost:5432/trading",
        description="Async SQLAlchemy URL for the primary (write) database.",
    )
    database_read_url: str = Field(
        default="",
        description="Async SQLAlchemy URL for the read replica. Defaults to write URL.",
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)

    @property
    def effective_read_url(self) -> str:
        """Return read URL, falling back to write URL when no replica is configured."""
        return self.database_read_url or self.database_write_url
