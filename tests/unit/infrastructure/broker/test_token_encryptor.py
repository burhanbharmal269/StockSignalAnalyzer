"""Unit tests for TokenEncryptor (AES-256-GCM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain.exceptions.broker import TokenEncryptionError
from core.infrastructure.broker.token_encryptor import TokenEncryptor

_TEST_KEY_HEX = "a" * 64


def _make_encryptor(key_hex: str = _TEST_KEY_HEX) -> TokenEncryptor:
    secrets = MagicMock()
    secrets.get_secret = AsyncMock(return_value=key_hex)
    return TokenEncryptor(secrets_client=secrets, key_secret_name="TEST_KEY")


class TestEncryptDecryptRoundtrip:
    async def test_roundtrip_short_string(self) -> None:
        enc = _make_encryptor()
        token = "access_token_12345"
        ciphertext = await enc.encrypt(token)
        plaintext = await enc.decrypt(ciphertext)
        assert plaintext == token

    async def test_roundtrip_long_string(self) -> None:
        enc = _make_encryptor()
        token = "x" * 500
        ciphertext = await enc.encrypt(token)
        assert await enc.decrypt(ciphertext) == token

    async def test_roundtrip_unicode(self) -> None:
        enc = _make_encryptor()
        token = "token_with_unicode_éàü"
        ciphertext = await enc.encrypt(token)
        assert await enc.decrypt(ciphertext) == token

    async def test_encrypt_produces_different_ciphertexts(self) -> None:
        enc = _make_encryptor()
        token = "same_token"
        ct1 = await enc.encrypt(token)
        ct2 = await enc.encrypt(token)
        assert ct1 != ct2

    async def test_ciphertext_is_not_plaintext(self) -> None:
        enc = _make_encryptor()
        token = "secret_access_token"
        ct = await enc.encrypt(token)
        assert token not in ct


class TestEncryptErrors:
    async def test_raises_on_wrong_key_length(self) -> None:
        enc = _make_encryptor(key_hex="abc123")
        with pytest.raises(TokenEncryptionError):
            await enc.encrypt("some_token")

    async def test_raises_on_secrets_client_failure(self) -> None:
        secrets = MagicMock()
        secrets.get_secret = AsyncMock(side_effect=Exception("vault unavailable"))
        enc = TokenEncryptor(secrets_client=secrets, key_secret_name="KEY")
        with pytest.raises(TokenEncryptionError):
            await enc.encrypt("token")


class TestDecryptErrors:
    async def test_raises_on_tampered_ciphertext(self) -> None:
        enc = _make_encryptor()
        ct = await enc.encrypt("original_token")
        tampered = ct[:-4] + "XXXX"
        with pytest.raises(TokenEncryptionError):
            await enc.decrypt(tampered)

    async def test_raises_on_truncated_ciphertext(self) -> None:
        enc = _make_encryptor()
        with pytest.raises(TokenEncryptionError):
            await enc.decrypt("dG9vc2hvcnQ=")

    async def test_raises_when_key_changes(self) -> None:
        enc1 = _make_encryptor(key_hex="a" * 64)
        enc2 = _make_encryptor(key_hex="b" * 64)
        ct = await enc1.encrypt("token_abc")
        with pytest.raises(TokenEncryptionError):
            await enc2.decrypt(ct)
