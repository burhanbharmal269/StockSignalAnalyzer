"""TokenEncryptor — AES-256-GCM encryption for broker access tokens.

The encryption key is fetched at runtime from ISecretsClient (never hardcoded
or stored in the database). This satisfies:
    docs/23_SECURITY_BASELINE.md §1.1 Broker Access Token Encryption

Key format in secrets store: 64 hexadecimal characters (32 bytes).
Output format: URL-safe base64(12-byte nonce || ciphertext+tag).
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.domain.exceptions.broker import TokenEncryptionError
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.domain.interfaces.i_secrets_client import ISecretsClient

logger = get_logger(__name__)

_NONCE_BYTES = 12
_KEY_HEX_LEN = 64


class TokenEncryptor:
    """AES-256-GCM symmetric encryption for broker session tokens.

    Construction:
        encryptor = TokenEncryptor(secrets_client, key_secret_name)

    Encryption key lifecycle:
        - Key is fetched from ISecretsClient on every encrypt/decrypt call.
        - Key is never cached in memory beyond a single operation.
        - Key rotation: update the secret in the secrets store; old sessions
          encrypted with the previous key will fail decrypt (by design —
          operators re-authenticate after key rotation).
    """

    def __init__(
        self,
        secrets_client: ISecretsClient,
        key_secret_name: str,
    ) -> None:
        self._secrets = secrets_client
        self._key_secret_name = key_secret_name

    async def encrypt(self, plaintext: str) -> str:
        """Encrypt *plaintext* and return a URL-safe base64-encoded ciphertext.

        Format: base64url(nonce[12] || ciphertext+tag)

        Raises:
            TokenEncryptionError: On key retrieval failure or cipher error.
        """
        try:
            key = await self._load_key()
            nonce = os.urandom(_NONCE_BYTES)
            aesgcm = AESGCM(key)
            cipher_bytes = aesgcm.encrypt(nonce, plaintext.encode(), None)
            return base64.urlsafe_b64encode(nonce + cipher_bytes).decode()
        except TokenEncryptionError:
            raise
        except Exception as exc:
            logger.error("token_encryptor.encrypt.failed")
            msg = f"Token encryption failed: {exc}"
            raise TokenEncryptionError(msg) from exc

    async def decrypt(self, encrypted: str) -> str:
        """Decrypt a ciphertext produced by :meth:`encrypt`.

        Raises:
            TokenEncryptionError: On key retrieval failure, invalid ciphertext,
                or authentication tag mismatch (tampering detected).
        """
        try:
            key = await self._load_key()
            raw = base64.urlsafe_b64decode(encrypted.encode())
            if len(raw) < _NONCE_BYTES:
                msg = "Ciphertext too short to contain a nonce."
                raise TokenEncryptionError(msg)
            nonce = raw[:_NONCE_BYTES]
            cipher_bytes = raw[_NONCE_BYTES:]
            aesgcm = AESGCM(key)
            plaintext_bytes = aesgcm.decrypt(nonce, cipher_bytes, None)
            return plaintext_bytes.decode()
        except TokenEncryptionError:
            raise
        except Exception as exc:
            logger.error("token_encryptor.decrypt.failed")
            msg = f"Token decryption failed: {exc}"
            raise TokenEncryptionError(msg) from exc

    async def _load_key(self) -> bytes:
        hex_key = await self._secrets.get_secret(self._key_secret_name)
        if len(hex_key) != _KEY_HEX_LEN:
            msg = (
                f"Encryption key must be {_KEY_HEX_LEN} hex characters "
                f"(32 bytes); got {len(hex_key)} chars."
            )
            raise TokenEncryptionError(msg)
        return bytes.fromhex(hex_key)
