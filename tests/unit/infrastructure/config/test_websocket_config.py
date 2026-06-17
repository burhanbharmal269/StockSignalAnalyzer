"""Unit tests for WebSocketConfig."""

from __future__ import annotations

from core.infrastructure.config.websocket_config import WebSocketConfig


class TestWebSocketConfig:
    def test_defaults(self) -> None:
        config = WebSocketConfig()
        assert config.websocket_max_reconnect_attempts == 5
        assert config.websocket_ping_interval_seconds == 3
        assert config.websocket_ping_timeout_seconds == 2
        assert config.websocket_tick_stale_threshold_seconds == 30
        assert config.websocket_tick_warn_threshold_seconds == 10
        assert config.websocket_subscription_batch_debounce_ms == 100
        assert config.websocket_max_subscriptions_per_connection == 3000

    def test_env_override(self, monkeypatch: object) -> None:
        import pytest
        if not hasattr(pytest, "MonkeyPatch"):
            return
        import os
        os.environ["WEBSOCKET_MAX_RECONNECT_ATTEMPTS"] = "3"
        os.environ["WEBSOCKET_MAX_SUBSCRIPTIONS_PER_CONNECTION"] = "1000"
        try:
            config = WebSocketConfig()
            assert config.websocket_max_reconnect_attempts == 3
            assert config.websocket_max_subscriptions_per_connection == 1000
        finally:
            os.environ.pop("WEBSOCKET_MAX_RECONNECT_ATTEMPTS", None)
            os.environ.pop("WEBSOCKET_MAX_SUBSCRIPTIONS_PER_CONNECTION", None)
