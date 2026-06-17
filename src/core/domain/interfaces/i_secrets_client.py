"""ISecretsClient — domain port for secrets retrieval.

Implementations live in infrastructure/secrets/. The domain and application
layers depend only on this interface, never on a concrete vault or AWS client.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Dependency Inversion)
           docs/23_SECURITY_BASELINE.md (Section 3 — Secrets Management)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ISecretsClient(ABC):
    """Port for fetching secrets from an external secrets store.

    Secrets are retrieved by name at runtime; never read from env vars
    directly inside domain or application code.
    """

    @abstractmethod
    async def get_secret(self, secret_name: str) -> str:
        """Return the plaintext value for *secret_name*.

        Raises:
            SecretNotFoundError: if the secret does not exist.
            SecretsClientError: on backend connectivity failure.
        """

    @abstractmethod
    async def get_secret_json(self, secret_name: str) -> dict[str, str]:
        """Return a JSON secret parsed into a string→string mapping.

        Raises:
            SecretNotFoundError: if the secret does not exist.
            SecretsClientError: on backend connectivity failure or malformed JSON.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the secrets backend is reachable, False otherwise."""
