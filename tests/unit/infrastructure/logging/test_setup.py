"""Unit tests for structured logging setup."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from core.infrastructure.logging.setup import (
    configure_logging,
    secrets_scrubber,
)


class TestSecretsScubber:
    """Verify the secrets scrubber redacts sensitive data."""

    def _run(self, event_dict: dict) -> dict:  # type: ignore[type-arg]
        """Helper: run scrubber processor and return the modified dict."""
        return secrets_scrubber(None, "info", event_dict)  # type: ignore[arg-type]

    def test_redacts_password_field(self) -> None:
        result = self._run({"event": "login", "password": "hunter2"})
        assert result["password"] == "[REDACTED]"

    def test_redacts_token_field(self) -> None:
        result = self._run({"event": "auth", "token": "abc123"})
        assert result["token"] == "[REDACTED]"

    def test_redacts_api_key_field(self) -> None:
        result = self._run({"event": "call", "api_key": "secret-value"})
        assert result["api_key"] == "[REDACTED]"

    def test_redacts_openai_key_in_value(self) -> None:
        result = self._run({"event": "ai_call", "key": "sk-abcdefghij1234567890ABCDE"})
        assert result["key"] == "[REDACTED]"

    def test_redacts_bearer_token_in_value(self) -> None:
        result = self._run({"event": "req", "authorization": "Bearer eyJhbGciOi"})
        assert result["authorization"] == "[REDACTED]"

    def test_preserves_non_sensitive_fields(self) -> None:
        result = self._run({"event": "trade", "symbol": "NIFTY", "score": 82})
        assert result["symbol"] == "NIFTY"
        assert result["score"] == 82

    def test_preserves_event_field(self) -> None:
        result = self._run({"event": "signal.generated", "direction": "LONG"})
        assert result["event"] == "signal.generated"

    def test_non_string_values_are_not_modified(self) -> None:
        result = self._run({"event": "check", "count": 42, "active": True})
        assert result["count"] == 42
        assert result["active"] is True


class TestConfigureLogging:
    """Verify logging configuration produces correct output format."""

    def test_configure_sets_root_log_level(self) -> None:
        configure_logging(log_level="WARNING", log_format="console")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_configure_with_json_format_does_not_raise(self) -> None:
        configure_logging(log_level="INFO", log_format="json")

    def test_configure_with_console_format_does_not_raise(self) -> None:
        configure_logging(log_level="DEBUG", log_format="console")

    def test_structlog_is_configured_after_setup(self) -> None:
        configure_logging(log_level="INFO", log_format="json")
        logger = structlog.get_logger("test")
        assert logger is not None

    def test_json_format_produces_parseable_output(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(log_level="INFO", log_format="json")
        log = structlog.get_logger("test.json")
        log.info("test_event", symbol="NIFTY", score=82)

        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        assert lines, "Expected at least one log line"
        parsed = json.loads(lines[-1])
        assert parsed.get("event") == "test_event"
        assert parsed.get("symbol") == "NIFTY"
        assert parsed.get("score") == 82

    def test_json_log_scrubs_password(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(log_level="INFO", log_format="json")
        log = structlog.get_logger("test.scrub")
        log.info("auth_attempt", password="secret123")

        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().splitlines() if ln.strip()]
        parsed = json.loads(lines[-1])
        assert parsed.get("password") == "[REDACTED]"
        assert "secret123" not in captured.out
