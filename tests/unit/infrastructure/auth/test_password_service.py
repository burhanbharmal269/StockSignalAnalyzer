"""Unit tests for PasswordService (Argon2id hashing)."""

from __future__ import annotations

import pytest

from core.infrastructure.auth.password_service import PasswordService


@pytest.fixture()
def svc() -> PasswordService:
    return PasswordService()


class TestHashPassword:
    def test_returns_argon2_hash(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("secret")
        assert hashed.startswith("$argon2id$")

    def test_different_salts_for_same_input(self, svc: PasswordService) -> None:
        h1 = svc.hash_password("same_password")
        h2 = svc.hash_password("same_password")
        assert h1 != h2

    def test_empty_string_hashes_without_error(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("")
        assert hashed.startswith("$argon2id$")


class TestVerifyPassword:
    def test_correct_password_returns_true(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("my_pass")
        assert svc.verify_password("my_pass", hashed) is True

    def test_wrong_password_returns_false(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("correct")
        assert svc.verify_password("wrong", hashed) is False

    def test_empty_plain_against_nonempty_hash_returns_false(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("nonempty")
        assert svc.verify_password("", hashed) is False

    def test_invalid_hash_string_returns_false(self, svc: PasswordService) -> None:
        assert svc.verify_password("any", "not_a_hash") is False

    def test_never_raises_on_garbage_hash(self, svc: PasswordService) -> None:
        result = svc.verify_password("plain", "$argon2id$garbage")
        assert result is False


class TestNeedsRehash:
    def test_fresh_hash_does_not_need_rehash(self, svc: PasswordService) -> None:
        hashed = svc.hash_password("value")
        assert svc.needs_rehash(hashed) is False

    def test_outdated_parameters_needs_rehash(self, svc: PasswordService) -> None:
        from argon2 import PasswordHasher

        old_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
        old_hash = old_hasher.hash("value")
        assert svc.needs_rehash(old_hash) is True
