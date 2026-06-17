"""Unit tests for SecurityConfig."""

from __future__ import annotations

import pytest

from core.infrastructure.config.security_config import SecurityConfig, get_security_config


class TestSecurityConfig:
    def test_default_access_token_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        config = SecurityConfig()
        assert config.access_token_ttl_seconds == 900

    def test_default_refresh_token_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        config = SecurityConfig()
        assert config.refresh_token_ttl_seconds == 604800

    def test_default_algorithm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        config = SecurityConfig()
        assert config.algorithm == "HS256"

    def test_default_max_login_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        config = SecurityConfig()
        assert config.max_login_attempts == 5

    def test_secret_key_too_short_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "short")
        with pytest.raises(Exception):  # noqa: B017
            SecurityConfig()

    def test_secret_key_exactly_32_chars_is_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        config = SecurityConfig()
        assert config.secret_key.get_secret_value() == "a" * 32

    def test_secret_key_not_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        config = SecurityConfig()
        assert "a" * 32 not in repr(config)

    def test_admin_ip_list_parsed_from_comma_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("ALLOWED_ADMIN_IPS", "127.0.0.1/32,10.0.0.0/8")
        config = SecurityConfig()
        assert config.admin_ip_list == ["127.0.0.1/32", "10.0.0.0/8"]

    def test_admin_ip_list_single_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("ALLOWED_ADMIN_IPS", "127.0.0.1/32")
        config = SecurityConfig()
        assert config.admin_ip_list == ["127.0.0.1/32"]

    def test_admin_ip_list_empty_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("ALLOWED_ADMIN_IPS", "")
        config = SecurityConfig()
        assert config.admin_ip_list == []

    def test_cors_origin_list_parsed_from_comma_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,https://app.example.com")
        config = SecurityConfig()
        assert "http://localhost:3000" in config.cors_origin_list
        assert "https://app.example.com" in config.cors_origin_list

    def test_get_security_config_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        get_security_config.cache_clear()
        c1 = get_security_config()
        c2 = get_security_config()
        assert c1 is c2
        get_security_config.cache_clear()
