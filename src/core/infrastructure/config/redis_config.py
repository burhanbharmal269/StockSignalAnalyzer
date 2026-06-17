"""Redis connection configuration loaded from environment variables.

REDIS_URL        — Redis URL (default: redis://localhost:6379/0)
REDIS_MAX_CONNECTIONS — connection pool size (default: 20)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL.",
    )
    redis_max_connections: int = Field(default=20, ge=1, le=200)
    redis_decode_responses: bool = Field(default=True)
