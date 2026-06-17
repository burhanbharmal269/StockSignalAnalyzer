"""PasswordService — Argon2id hash and verification.

Uses Argon2id with parameters from Doc 23 §2:
  memory_cost = 65536 KiB (64 MiB)
  time_cost   = 3 iterations
  parallelism = 4 threads

Never stores or logs plain-text passwords. The caller is responsible for
zeroing the plain-text string from memory after calling hash_password().
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordService:
    """Argon2id password hashing and verification.

    Inject via the DI container — never instantiate directly in routes.
    """

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
        )

    def hash_password(self, plain: str) -> str:
        """Return an Argon2id hash of plain.

        The returned hash includes the salt and algorithm parameters and is
        safe to store in the database as-is.
        """
        return self._hasher.hash(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        """Return True if plain matches hashed; False otherwise.

        Never raises — all Argon2 exceptions are caught and mapped to False.
        """
        try:
            return self._hasher.verify(hashed, plain)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """Return True if hashed was created with outdated Argon2 parameters.

        Call after a successful verify_password() and re-hash if True.
        """
        return self._hasher.check_needs_rehash(hashed)
