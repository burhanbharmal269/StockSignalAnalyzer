"""Domain exceptions for secrets retrieval failures."""

from __future__ import annotations

from core.domain.exceptions.base import DomainError


class SecretsClientError(DomainError):
    """Raised when the secrets backend is unreachable or returns an error."""


class SecretNotFoundError(SecretsClientError):
    """Raised when the requested secret name does not exist in the store."""

    def __init__(self, secret_name: str) -> None:
        super().__init__(f"Secret not found: {secret_name!r}")
        self.secret_name = secret_name
