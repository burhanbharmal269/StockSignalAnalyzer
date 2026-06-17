"""Unit tests for AppSettings configuration loading."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.infrastructure.config.settings import (
    AppSettings,
    Environment,
    LogFormat,
    LogLevel,
)


class TestAppSettingsDefaults:
    """Verify defaults are correct when no env vars are set."""

    def test_default_app_name(self) -> None:
        settings = AppSettings()
        assert settings.app_name == "StockSignalAnalyzer"

    def test_default_environment_is_development(self) -> None:
        settings = AppSettings()
        assert settings.environment == Environment.DEVELOPMENT

    def test_default_debug_is_false(self) -> None:
        settings = AppSettings()
        assert settings.debug is False

    def test_default_api_port(self) -> None:
        settings = AppSettings()
        assert settings.api_port == 8000

    def test_default_log_level_is_info(self) -> None:
        settings = AppSettings()
        assert settings.log_level == LogLevel.INFO

    def test_default_log_format_is_console(self) -> None:
        settings = AppSettings()
        assert settings.log_format == LogFormat.CONSOLE


class TestAppSettingsEnvOverrides:
    """Verify environment variables are correctly picked up."""

    def test_environment_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "staging")
        settings = AppSettings()
        assert settings.environment == Environment.STAGING

    def test_log_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        settings = AppSettings()
        assert settings.log_level == LogLevel.WARNING

    def test_api_port_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "9000")
        settings = AppSettings()
        assert settings.api_port == 9000

    def test_debug_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "true")
        settings = AppSettings()
        assert settings.debug is True


class TestAppSettingsValidation:
    """Verify validation rules are enforced."""

    def test_production_rejects_console_log_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_FORMAT", "console")
        monkeypatch.setenv("DEBUG", "false")
        with pytest.raises(ValidationError, match="LOG_FORMAT must be 'json'"):
            AppSettings()

    def test_production_rejects_debug_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("DEBUG", "true")
        with pytest.raises(ValidationError, match="DEBUG must be False"):
            AppSettings()

    def test_production_accepts_json_log_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("DEBUG", "false")
        settings = AppSettings()
        assert settings.log_format == LogFormat.JSON

    def test_api_port_below_minimum_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_PORT", "80")
        with pytest.raises(ValidationError):
            AppSettings()


class TestAppSettingsProperties:
    """Verify computed properties return correct values."""

    def test_is_production_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("DEBUG", "false")
        settings = AppSettings()
        assert settings.is_production is True
        assert settings.is_development is False

    def test_is_development_true(self) -> None:
        settings = AppSettings()
        assert settings.is_development is True
        assert settings.is_production is False

    def test_is_debug_reflects_debug_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEBUG", "true")
        settings = AppSettings()
        assert settings.is_debug is True


class TestSettingsSingleton:
    """Verify get_settings() caching behaviour."""

    def test_returns_same_instance_on_repeated_calls(self) -> None:
        from core.infrastructure.config.settings import get_settings

        first = get_settings()
        second = get_settings()
        assert first is second

    def test_cache_clear_allows_fresh_load(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.infrastructure.config.settings import get_settings

        monkeypatch.setenv("APP_NAME", "TestPlatform")
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.app_name == "TestPlatform"
