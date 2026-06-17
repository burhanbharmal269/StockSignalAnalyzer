"""Unit tests for JWTService — HS256 token creation, decoding, and revocation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from pydantic import SecretStr

from core.infrastructure.auth.jwt_service import JWTService, TokenError
from core.infrastructure.config.security_config import SecurityConfig


def _make_config(**overrides: object) -> SecurityConfig:
    defaults = {
        "secret_key": "test-secret-key-that-is-long-enough-for-hmac",
        "jwt_private_key_pem": None,
        "jwt_public_key_pem": None,
        "access_token_ttl_seconds": 900,
        "refresh_token_ttl_seconds": 86400,
    }
    defaults.update(overrides)
    return SecurityConfig(**defaults)  # type: ignore[arg-type]


def _make_redis() -> MagicMock:
    r = MagicMock()
    r.setex = AsyncMock()
    r.exists = AsyncMock(return_value=0)
    return r


@pytest.fixture()
def config() -> SecurityConfig:
    return _make_config()


@pytest.fixture()
def redis() -> MagicMock:
    return _make_redis()


@pytest.fixture()
def svc(config: SecurityConfig, redis: MagicMock) -> JWTService:
    return JWTService(config=config, redis_client=redis)


class TestAlgorithmSelection:
    def test_hs256_when_no_pem_keys(self, svc: JWTService) -> None:
        assert svc._algorithm() == "HS256"

    def test_rs256_when_pem_keys_configured(self, config: SecurityConfig) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        rs_config = _make_config(
            jwt_private_key_pem=SecretStr(private_pem),
            jwt_public_key_pem=public_pem,
        )
        rs_svc = JWTService(config=rs_config, redis_client=_make_redis())
        assert rs_svc._algorithm() == "RS256"


class TestCreateAccessToken:
    def test_returns_token_and_jti(self, svc: JWTService) -> None:
        token, jti = svc.create_access_token("user-1", "admin", "ADMIN", False)
        assert isinstance(token, str)
        assert isinstance(jti, str)
        assert len(token) > 0

    def test_token_contains_expected_claims(self, svc: JWTService) -> None:
        token, jti = svc.create_access_token("user-1", "testuser", "VIEWER", True)
        claims = svc.decode_token(token)
        assert claims["sub"] == "user-1"
        assert claims["username"] == "testuser"
        assert claims["role"] == "VIEWER"
        assert claims["force_change"] is True
        assert claims["jti"] == jti

    def test_unique_jti_per_call(self, svc: JWTService) -> None:
        _, jti1 = svc.create_access_token("u", "user", "ADMIN", False)
        _, jti2 = svc.create_access_token("u", "user", "ADMIN", False)
        assert jti1 != jti2


class TestCreateRefreshToken:
    def test_returns_token_and_jti(self, svc: JWTService) -> None:
        token, jti = svc.create_refresh_token("user-2")
        assert isinstance(token, str)
        assert len(jti) > 0

    def test_refresh_token_has_type_claim(self, svc: JWTService) -> None:
        token, _ = svc.create_refresh_token("user-2")
        claims = svc.decode_token(token)
        assert claims["type"] == "refresh"
        assert claims["sub"] == "user-2"


class TestDecodeToken:
    def test_valid_token_decodes_successfully(self, svc: JWTService) -> None:
        token, _ = svc.create_access_token("u", "user", "ADMIN", False)
        claims = svc.decode_token(token)
        assert claims["sub"] == "u"

    def test_tampered_token_raises_token_error(self, svc: JWTService) -> None:
        token, _ = svc.create_access_token("u", "user", "ADMIN", False)
        tampered = token[:-4] + "xxxx"
        with pytest.raises(TokenError):
            svc.decode_token(tampered)

    def test_expired_token_raises_token_error(self, svc: JWTService) -> None:
        from datetime import UTC, datetime, timedelta

        secret = svc._config.secret_key.get_secret_value()
        payload = {
            "sub": "u",
            "role": "ADMIN",
            "force_change": False,
            "jti": str(uuid.uuid4()),
            "iat": datetime.now(UTC) - timedelta(seconds=7200),
            "exp": datetime.now(UTC) - timedelta(seconds=3600),
            "iss": "stocksignalanalyzer",
            "aud": "stocksignalanalyzer",
        }
        expired_token = pyjwt.encode(payload, secret, algorithm="HS256")
        with pytest.raises(TokenError, match="expired"):
            svc.decode_token(expired_token)

    def test_garbage_string_raises_token_error(self, svc: JWTService) -> None:
        with pytest.raises(TokenError):
            svc.decode_token("not.a.token")

    def test_wrong_secret_raises_token_error(self, svc: JWTService) -> None:
        other_config = _make_config(secret_key="completely-different-secret-key-value")
        other_svc = JWTService(config=other_config, redis_client=_make_redis())
        token, _ = other_svc.create_access_token("u", "user", "ADMIN", False)
        with pytest.raises(TokenError):
            svc.decode_token(token)

    def test_audience_verified(self, svc: JWTService) -> None:
        """Token with a wrong audience must be rejected."""
        secret = svc._config.secret_key.get_secret_value()
        import uuid as _uuid
        from datetime import UTC, datetime, timedelta

        payload = {
            "sub": "u",
            "jti": str(_uuid.uuid4()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(seconds=900),
            "iss": "stocksignalanalyzer",
            "aud": "wrong_audience",
        }
        bad_token = pyjwt.encode(payload, secret, algorithm="HS256")
        with pytest.raises(TokenError):
            svc.decode_token(bad_token)


class TestRevocation:
    async def test_revoke_calls_setex(self, svc: JWTService, redis: MagicMock) -> None:
        await svc.revoke("jti-abc", 900)
        redis.setex.assert_awaited_once_with("auth:revoked:jti-abc", 900, "1")

    async def test_is_revoked_true_when_key_exists(
        self, svc: JWTService, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=1)
        assert await svc.is_revoked("jti-abc") is True

    async def test_is_revoked_false_when_key_absent(
        self, svc: JWTService, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=0)
        assert await svc.is_revoked("jti-abc") is False

    async def test_is_revoked_checks_correct_key(
        self, svc: JWTService, redis: MagicMock
    ) -> None:
        redis.exists = AsyncMock(return_value=0)
        await svc.is_revoked("my-jti")
        call_key = redis.exists.call_args[0][0]
        assert call_key == "auth:revoked:my-jti"
