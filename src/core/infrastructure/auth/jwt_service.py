"""JWTService — sign, verify, and revoke JWT tokens.

Algorithm selection (Doc 23 §4.1):
  - RS256 when jwt_private_key_pem + jwt_public_key_pem are configured (production).
  - HS256 fallback when only secret_key is set (local development).

Token revocation uses a Redis SET keyed by the JWT's jti claim:
  auth:revoked:{jti}  →  "1"  (TTL = remaining token lifetime)

Every authenticated request checks this set, adding ~1 ms latency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from redis.asyncio import Redis

from core.infrastructure.config.security_config import SecurityConfig

# Audience / issuer constants — not hardcoded values, just logical names used
# as JWT claims to scope tokens to this application.
_AUDIENCE = "stocksignalanalyzer"
_ISSUER = "stocksignalanalyzer"

_REVOKE_PREFIX = "auth:revoked:"


class TokenError(Exception):
    """Raised when a JWT cannot be verified (expired, tampered, revoked)."""


class JWTService:
    """Sign and verify JWT access/refresh tokens.

    Inject via the DI container — never instantiate directly in routes.
    """

    def __init__(self, config: SecurityConfig, redis_client: Redis) -> None:  # type: ignore[type-arg]
        self._config = config
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _signing_key(self) -> str:
        if self._config.jwt_private_key_pem is not None:
            return self._config.jwt_private_key_pem.get_secret_value()
        return self._config.secret_key.get_secret_value()

    def _verification_key(self) -> str:
        if self._config.jwt_public_key_pem is not None:
            return self._config.jwt_public_key_pem
        return self._config.secret_key.get_secret_value()

    def _algorithm(self) -> str:
        return self._config.jwt_algorithm

    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------

    def create_access_token(
        self, user_id: str, username: str, role: str, force_change: bool
    ) -> tuple[str, str]:
        """Return (encoded_token, jti).

        Args:
            user_id:      UUID string identifying the user.
            username:     Human-readable username included in claims for logging.
            role:         "ADMIN" or "VIEWER".
            force_change: True when the operator must change the generated password.
        """
        jti = str(uuid.uuid4())
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": user_id,
            "username": username,
            "role": role,
            "force_change": force_change,
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(seconds=self._config.access_token_ttl_seconds),
            "iss": _ISSUER,
            "aud": _AUDIENCE,
        }
        token: str = jwt.encode(payload, self._signing_key(), algorithm=self._algorithm())
        return token, jti

    def create_refresh_token(self, user_id: str) -> tuple[str, str]:
        """Return (encoded_token, jti) for a long-lived refresh token."""
        jti = str(uuid.uuid4())
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": user_id,
            "type": "refresh",
            "jti": jti,
            "iat": now,
            "exp": now + timedelta(seconds=self._config.refresh_token_ttl_seconds),
            "iss": _ISSUER,
            "aud": _AUDIENCE,
        }
        token: str = jwt.encode(payload, self._signing_key(), algorithm=self._algorithm())
        return token, jti

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def decode_token(self, token: str) -> dict[str, Any]:
        """Decode and verify token signature and expiry.

        Raises:
            TokenError: if the token is malformed, expired, or has a bad signature.
        """
        try:
            return jwt.decode(
                token,
                self._verification_key(),
                algorithms=[self._algorithm()],
                audience=_AUDIENCE,
                issuer=_ISSUER,
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError(f"Invalid token: {exc}") from exc

    # ------------------------------------------------------------------
    # Revocation (Redis blocklist)
    # ------------------------------------------------------------------

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Add jti to the Redis revocation set with a TTL."""
        await self._redis.setex(_REVOKE_PREFIX + jti, ttl_seconds, "1")

    async def is_revoked(self, jti: str) -> bool:
        """Return True if jti is in the Redis revocation set."""
        return bool(await self._redis.exists(_REVOKE_PREFIX + jti))
