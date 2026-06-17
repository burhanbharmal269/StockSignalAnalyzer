"""Unit tests for User domain entity."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.domain.entities.user import User
from core.domain.enums.user_role import UserRole


def _make_user(**overrides: object) -> User:
    defaults: dict = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "username": "testuser",
        "hashed_password": "$argon2id$hash",
        "role": UserRole.VIEWER,
        "is_active": True,
        "force_change": False,
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


class TestUserEntity:
    def test_creation_with_defaults(self) -> None:
        user = _make_user()
        assert user.username == "testuser"
        assert user.role == UserRole.VIEWER
        assert user.is_active is True
        assert user.force_change is False
        assert user.last_login_at is None

    def test_created_at_defaults_to_now(self) -> None:
        before = datetime.now(UTC)
        user = _make_user()
        after = datetime.now(UTC)
        assert before <= user.created_at <= after

    def test_explicit_created_at(self) -> None:
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        user = _make_user(created_at=ts)
        assert user.created_at == ts

    def test_frozen_dataclass_immutable(self) -> None:
        user = _make_user()
        with pytest.raises((AttributeError, TypeError)):
            user.username = "hacked"  # type: ignore[misc]

    def test_admin_role(self) -> None:
        user = _make_user(role=UserRole.ADMIN)
        assert user.role == UserRole.ADMIN

    def test_force_change_true(self) -> None:
        user = _make_user(force_change=True)
        assert user.force_change is True

    def test_inactive_user(self) -> None:
        user = _make_user(is_active=False)
        assert user.is_active is False

    def test_last_login_at_set(self) -> None:
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        user = _make_user(last_login_at=ts)
        assert user.last_login_at == ts


class TestUserRole:
    def test_admin_value(self) -> None:
        assert UserRole.ADMIN == "ADMIN"

    def test_viewer_value(self) -> None:
        assert UserRole.VIEWER == "VIEWER"

    def test_is_str_enum(self) -> None:
        assert isinstance(UserRole.ADMIN, str)
