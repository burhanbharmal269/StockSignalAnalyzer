"""EnvSecretsClient — ISecretsClient backed by environment variables.

Used in development and CI. In production, replace with AwsSecretsClient
or HashiCorpVaultSecretsClient. The switch requires only a container
provider update — no application or domain code changes.

Reference: docs/23_SECURITY_BASELINE.md (Section 3)
"""

from __future__ import annotations

import json
import os

from core.domain.exceptions.secrets import SecretNotFoundError, SecretsClientError
from core.domain.interfaces.i_secrets_client import ISecretsClient


class EnvSecretsClient(ISecretsClient):
    """Reads secrets from environment variables.

    Secret names are uppercased and used directly as env var names.
    Example: get_secret("openai_api_key") reads os.environ["OPENAI_API_KEY"].
    """

    async def get_secret(self, secret_name: str) -> str:
        env_key = secret_name.upper()
        value = os.environ.get(env_key)
        if value is None:
            raise SecretNotFoundError(secret_name)
        return value

    async def get_secret_json(self, secret_name: str) -> dict[str, str]:
        raw = await self.get_secret(secret_name)
        try:
            parsed: dict[str, str] = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"Secret {secret_name!r} is not valid JSON: {exc}"
            raise SecretsClientError(msg) from exc
        return parsed

    async def health_check(self) -> bool:
        return True
