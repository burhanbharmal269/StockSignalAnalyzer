"""Unit tests for AIConfig."""

from __future__ import annotations

import pytest

from core.infrastructure.config.ai_config import AIConfig, get_ai_config


class TestAIConfig:
    def test_default_provider_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "disabled")
        config = AIConfig()
        assert config.ai_provider == "disabled"

    def test_is_enabled_false_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "disabled")
        config = AIConfig()
        assert config.is_enabled is False

    def test_is_enabled_true_for_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "openai")
        config = AIConfig()
        assert config.is_enabled is True

    def test_is_enabled_true_for_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        config = AIConfig()
        assert config.is_enabled is True

    def test_invalid_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "grok")
        with pytest.raises(Exception):  # noqa: B017
            AIConfig()

    def test_provider_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_PROVIDER", "OPENAI")
        config = AIConfig()
        assert config.ai_provider == "openai"

    def test_default_daily_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_DAILY_BUDGET_USD", raising=False)
        config = AIConfig()
        assert config.ai_daily_budget_usd == 5.00

    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_MODEL", raising=False)
        config = AIConfig()
        assert config.ai_model == "gpt-4o-mini"

    def test_api_keys_not_exposed_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretkey12345678901234567890")
        config = AIConfig()
        assert "sk-supersecretkey" not in repr(config)

    def test_get_ai_config_is_cached(self) -> None:
        get_ai_config.cache_clear()
        c1 = get_ai_config()
        c2 = get_ai_config()
        assert c1 is c2
        get_ai_config.cache_clear()
