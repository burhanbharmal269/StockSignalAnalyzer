"""Unit tests for BrokerSessionManager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from core.domain.entities.broker_session import BrokerSession
from core.infrastructure.broker.broker_session_manager import BrokerSessionManager


def _session(expired: bool = False, active: bool = True) -> BrokerSession:
    expires_at = (
        datetime.now(UTC) - timedelta(hours=1)
        if expired
        else datetime(2099, 12, 31, tzinfo=UTC)
    )
    s = BrokerSession.create(
        broker_name="paper",
        api_key="key",
        encrypted_access_token="enc_token",
        expires_at=expires_at,
    )
    if not active:
        s.deactivate()
    return s


def _make_mgr(
    login_returns: BrokerSession | None = None,
    profile_raises: Exception | None = None,
) -> tuple[BrokerSessionManager, MagicMock, MagicMock]:
    broker = MagicMock()
    repo = MagicMock()

    default_session = login_returns or _session()
    broker.broker_name = "paper"
    broker.login = AsyncMock(return_value=default_session)
    broker.logout = AsyncMock()
    if profile_raises:
        broker.get_profile = AsyncMock(side_effect=profile_raises)
    else:
        broker.get_profile = AsyncMock(return_value=MagicMock())

    repo.save = AsyncMock()
    repo.get_active = AsyncMock(return_value=default_session)
    repo.deactivate_all = AsyncMock()

    mgr = BrokerSessionManager(broker=broker, session_repository=repo)
    return mgr, broker, repo


class TestCreateSession:
    async def test_create_session_calls_deactivate_all_first(self) -> None:
        mgr, broker, repo = _make_mgr()
        await mgr.create_session("key", "req_token", "secret")
        repo.deactivate_all.assert_called_once_with("paper")

    async def test_create_session_calls_broker_login(self) -> None:
        mgr, broker, repo = _make_mgr()
        await mgr.create_session("key", "req_token", "secret")
        broker.login.assert_called_once_with(
            api_key="key", request_token="req_token", api_secret="secret"
        )

    async def test_create_session_saves_to_repo(self) -> None:
        mgr, broker, repo = _make_mgr()
        await mgr.create_session("key", "req_token", "secret")
        repo.save.assert_called_once()

    async def test_create_session_returns_broker_session(self) -> None:
        expected = _session()
        mgr, _, _ = _make_mgr(login_returns=expected)
        result = await mgr.create_session("key", "req_token", "secret")
        assert result is expected


class TestRefreshSession:
    async def test_refresh_deactivates_session(self) -> None:
        mgr, _, repo = _make_mgr()
        s = _session()
        assert s.is_active is True
        await mgr.refresh_session(s)
        assert s.is_active is False

    async def test_refresh_saves_deactivated_session(self) -> None:
        mgr, _, repo = _make_mgr()
        s = _session()
        await mgr.refresh_session(s)
        repo.save.assert_called_once_with(s)


class TestValidateSession:
    async def test_validate_active_unexpired_session_calls_profile(self) -> None:
        mgr, broker, _ = _make_mgr()
        s = _session()
        result = await mgr.validate_session(s)
        assert result is True
        broker.get_profile.assert_called_once_with(s)

    async def test_validate_expired_session_returns_false(self) -> None:
        mgr, broker, _ = _make_mgr()
        s = _session(expired=True)
        result = await mgr.validate_session(s)
        assert result is False
        broker.get_profile.assert_not_called()

    async def test_validate_inactive_session_returns_false(self) -> None:
        mgr, broker, _ = _make_mgr()
        s = _session(active=False)
        result = await mgr.validate_session(s)
        assert result is False
        broker.get_profile.assert_not_called()

    async def test_validate_profile_raises_returns_false(self) -> None:
        mgr, _, _ = _make_mgr(profile_raises=Exception("network error"))
        s = _session()
        result = await mgr.validate_session(s)
        assert result is False


class TestTerminateSession:
    async def test_terminate_calls_broker_logout(self) -> None:
        mgr, broker, _ = _make_mgr()
        s = _session()
        await mgr.terminate_session(s)
        broker.logout.assert_called_once_with(s)

    async def test_terminate_saves_session_after_logout(self) -> None:
        mgr, _, repo = _make_mgr()
        s = _session()
        await mgr.terminate_session(s)
        repo.save.assert_called_once_with(s)

    async def test_terminate_deactivates_even_if_logout_fails(self) -> None:
        mgr, broker, repo = _make_mgr()
        broker.logout = AsyncMock(side_effect=Exception("connection error"))
        s = _session()
        await mgr.terminate_session(s)
        # should still save and deactivate
        assert s.is_active is False
        repo.save.assert_called_once_with(s)
