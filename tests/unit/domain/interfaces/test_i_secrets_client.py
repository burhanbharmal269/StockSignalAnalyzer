"""Tests that ISecretsClient is a properly defined abstract interface."""

from __future__ import annotations

import inspect

import pytest

from core.domain.interfaces.i_secrets_client import ISecretsClient


class TestISecretsClientInterface:
    def test_is_abstract(self) -> None:
        assert inspect.isabstract(ISecretsClient)

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            ISecretsClient()  # type: ignore[abstract]

    def test_has_get_secret_method(self) -> None:
        assert hasattr(ISecretsClient, "get_secret")

    def test_has_get_secret_json_method(self) -> None:
        assert hasattr(ISecretsClient, "get_secret_json")

    def test_has_health_check_method(self) -> None:
        assert hasattr(ISecretsClient, "health_check")

    def test_concrete_implementation_must_implement_all_methods(self) -> None:
        class Incomplete(ISecretsClient):
            async def get_secret(self, secret_name: str) -> str:
                return ""

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]
