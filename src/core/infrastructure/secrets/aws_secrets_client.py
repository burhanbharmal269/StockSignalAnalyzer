"""AwsSecretsClient — ISecretsClient backed by AWS Secrets Manager.

Stub implementation. Will be wired in Phase 6 (Auth & Secrets) when
the production secrets backend is provisioned.

Reference: docs/23_SECURITY_BASELINE.md (Section 3)
"""

from __future__ import annotations

from core.domain.interfaces.i_secrets_client import ISecretsClient


class AwsSecretsClient(ISecretsClient):
    """AWS Secrets Manager adapter. Not yet implemented."""

    async def get_secret(self, secret_name: str) -> str:
        raise NotImplementedError("AwsSecretsClient is not yet implemented")

    async def get_secret_json(self, secret_name: str) -> dict[str, str]:
        raise NotImplementedError("AwsSecretsClient is not yet implemented")

    async def health_check(self) -> bool:
        raise NotImplementedError("AwsSecretsClient is not yet implemented")
