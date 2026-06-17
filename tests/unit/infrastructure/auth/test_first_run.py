"""Unit tests for FirstRunInitializer."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

from core.domain.entities.user import User
from core.domain.enums.user_role import UserRole
from core.infrastructure.auth.first_run import FirstRunInitializer, _print_credentials


def _make_repo(has_admin: bool = False) -> MagicMock:
    repo = MagicMock()
    repo.has_any_admin = AsyncMock(return_value=has_admin)
    repo.create = AsyncMock()
    return repo


def _make_password_service() -> MagicMock:
    svc = MagicMock()
    svc.hash_password = MagicMock(return_value="$argon2id$hashed")
    return svc


class TestFirstRunInitializer:
    async def test_skips_when_admin_exists(self) -> None:
        repo = _make_repo(has_admin=True)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        await initializer.run()

        repo.create.assert_not_awaited()

    async def test_creates_admin_when_none_exists(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        repo.create.assert_awaited_once()

    async def test_created_user_is_admin_role(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        created_user: User = repo.create.call_args[0][0]
        assert created_user.role == UserRole.ADMIN

    async def test_created_user_has_force_change(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        created_user: User = repo.create.call_args[0][0]
        assert created_user.force_change is True

    async def test_created_username_is_admin(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        created_user: User = repo.create.call_args[0][0]
        assert created_user.username == "admin"

    async def test_password_is_hashed_not_plain(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        created_user: User = repo.create.call_args[0][0]
        assert created_user.hashed_password == "$argon2id$hashed"

    async def test_idempotent_second_call_no_create(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        with patch("sys.stdout", new_callable=io.StringIO):
            await initializer.run()

        # Second call with admin now present
        repo.has_any_admin = AsyncMock(return_value=True)
        await initializer.run()

        # create called only once total
        assert repo.create.await_count == 1

    async def test_prints_credentials_to_stdout(self) -> None:
        repo = _make_repo(has_admin=False)
        svc = _make_password_service()
        initializer = FirstRunInitializer(user_repository=repo, password_service=svc)

        fake_stdout = io.StringIO()
        with patch("sys.stdout", fake_stdout):
            await initializer.run()

        output = fake_stdout.getvalue()
        assert "admin" in output
        assert "ADMIN CREDENTIALS" in output


class TestPrintCredentials:
    def test_banner_contains_username(self) -> None:
        fake_stdout = io.StringIO()
        with patch("sys.stdout", fake_stdout):
            _print_credentials("test-password-value")
        assert "admin" in fake_stdout.getvalue()

    def test_banner_contains_password(self) -> None:
        fake_stdout = io.StringIO()
        with patch("sys.stdout", fake_stdout):
            _print_credentials("my-super-secret-pass")
        assert "my-super-secret-pass" in fake_stdout.getvalue()

    def test_banner_structure(self) -> None:
        fake_stdout = io.StringIO()
        with patch("sys.stdout", fake_stdout):
            _print_credentials("pw")
        output = fake_stdout.getvalue()
        assert "╔" in output
        assert "╚" in output
