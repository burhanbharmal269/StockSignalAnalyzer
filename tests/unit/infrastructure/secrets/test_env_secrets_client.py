"""Unit tests for EnvSecretsClient."""

from __future__ import annotations

import json

import pytest

from core.domain.exceptions.secrets import SecretNotFoundError, SecretsClientError
from core.infrastructure.secrets.env_secrets_client import EnvSecretsClient


class TestEnvSecretsClient:
    @pytest.fixture
    def client(self) -> EnvSecretsClient:
        return EnvSecretsClient()

    async def test_get_secret_reads_env_var(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_SECRET", "my_value")
        result = await client.get_secret("my_secret")
        assert result == "my_value"

    async def test_get_secret_uppercases_name(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KITE_API_KEY", "abc123")
        result = await client.get_secret("kite_api_key")
        assert result == "abc123"

    async def test_get_secret_raises_not_found(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NONEXISTENT_SECRET", raising=False)
        with pytest.raises(SecretNotFoundError) as exc_info:
            await client.get_secret("nonexistent_secret")
        assert "nonexistent_secret" in str(exc_info.value)

    async def test_get_secret_json_parses_json(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {"api_key": "key123", "secret": "secret456"}
        monkeypatch.setenv("MY_JSON_SECRET", json.dumps(payload))
        result = await client.get_secret_json("my_json_secret")
        assert result == payload

    async def test_get_secret_json_raises_on_invalid_json(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BAD_JSON", "not-json{{{")
        with pytest.raises(SecretsClientError):
            await client.get_secret_json("bad_json")

    async def test_get_secret_json_raises_not_found(
        self, client: EnvSecretsClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_JSON", raising=False)
        with pytest.raises(SecretNotFoundError):
            await client.get_secret_json("missing_json")

    async def test_health_check_returns_true(self, client: EnvSecretsClient) -> None:
        assert await client.health_check() is True
