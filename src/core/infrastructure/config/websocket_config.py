"""WebSocket connection configuration loaded from environment variables.

All timing values, retry limits, and capacity limits are configurable.
No magic numbers exist in the WebSocket infrastructure code.

Reference: docs/12_WEBSOCKET_MANAGER.md
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSocketConfig(BaseSettings):
    """WebSocket manager runtime configuration.

    All fields are overridable via environment variables prefixed by their name.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    websocket_max_reconnect_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum reconnection attempts before entering FAILED state.",
    )
    websocket_ping_interval_seconds: int = Field(
        default=3,
        ge=1,
        le=60,
        description="Broker ping frame interval in seconds.",
    )
    websocket_ping_timeout_seconds: int = Field(
        default=2,
        ge=1,
        le=30,
        description="Seconds to respond to a ping before treating connection as dead.",
    )
    websocket_tick_stale_threshold_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="No tick in this window triggers RECONNECTING during market hours.",
    )
    websocket_tick_warn_threshold_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description="No tick in this window logs a WARNING during market hours.",
    )
    websocket_subscription_batch_debounce_ms: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Milliseconds to coalesce subscribe/unsubscribe calls before sending.",
    )
    websocket_max_subscriptions_per_connection: int = Field(
        default=3000,
        ge=1,
        le=10000,
        description="Maximum instrument subscriptions per WebSocket connection.",
    )
