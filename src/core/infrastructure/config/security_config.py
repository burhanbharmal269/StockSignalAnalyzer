"""SecurityConfig — pydantic-settings model for security parameters.

Read from environment variables / .env at startup.
JWT secrets, admin IP allowlists, and brute-force parameters live here.
Broker tokens are NOT stored here — they are fetched via ISecretsClient.

List env vars (ALLOWED_ADMIN_IPS, CORS_ALLOWED_ORIGINS) accept
comma-separated strings: "127.0.0.1/32,10.0.0.0/8"

Reference: docs/23_SECURITY_BASELINE.md
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecurityConfig(BaseSettings):
    """Security-related configuration.

    SECRET_KEY must be at least 32 bytes of random entropy.
    In production, rotate it via env var update + rolling restart.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # JWT
    secret_key: SecretStr = Field(
        default=SecretStr("CHANGE_ME_IN_PRODUCTION_USE_32_RANDOM_BYTES"),
        description="HMAC signing key for JWT tokens. MUST be overridden in prod.",
    )
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    algorithm: str = Field(default="HS256")

    # Admin access — stored as comma-separated string; parsed via computed_field
    allowed_admin_ips: str = Field(
        default="",
        description="Comma-separated CIDR blocks allowed to access /admin routes.",
    )

    # RS256 asymmetric JWT keys (production).
    # When both are provided, jwt_algorithm returns "RS256" and these keys are used
    # for signing/verification. Falls back to HS256 + secret_key in development.
    jwt_private_key_pem: SecretStr | None = Field(
        default=None,
        description="RS256 RSA private key (PEM). Source from Secrets Manager in production.",
    )
    jwt_public_key_pem: str | None = Field(
        default=None,
        description="RS256 RSA public key (PEM). May be distributed to verifying services.",
    )

    # Brute-force protection
    max_login_attempts: int = Field(default=5, ge=1, le=100)
    login_attempt_window_seconds: int = Field(default=600, ge=60, le=3600)
    lockout_duration_seconds: int = Field(default=1800, ge=60, le=86400)

    # CORS — stored as comma-separated string; parsed via computed_field
    cors_allowed_origins: str = Field(
        default="http://localhost:3000",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jwt_algorithm(self) -> str:
        """Returns 'RS256' when PEM keys are configured, 'HS256' otherwise.

        Use RS256 in all non-development environments (Doc 23 §4.1).
        """
        if self.jwt_private_key_pem is not None and self.jwt_public_key_pem is not None:
            return "RS256"
        return "HS256"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def admin_ip_list(self) -> list[str]:
        """Parsed list of admin CIDR blocks."""
        return [ip.strip() for ip in self.allowed_admin_ips.split(",") if ip.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed list of allowed CORS origins."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @field_validator("secret_key", mode="before")
    @classmethod
    def secret_key_minimum_length(cls, value: object) -> object:
        raw = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
        if len(raw) < 32:
            msg = "SECRET_KEY must be at least 32 characters"
            raise ValueError(msg)
        return value


@lru_cache(maxsize=1)
def get_security_config() -> SecurityConfig:
    return SecurityConfig()
