"""BrokerSessionManager — IBrokerSessionManager implementation.

Orchestrates full broker session lifecycle:
  create  → broker.login() → encrypt → persist
  refresh → deactivate old → broker.login() with new request_token
  validate → not expired + not deactivated + broker.get_profile() ok
  terminate → broker.logout() → deactivate in repository

Reference: docs/23_SECURITY_BASELINE.md §1.1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.domain.interfaces.i_broker_session_manager import IBrokerSessionManager

if TYPE_CHECKING:
    from core.domain.entities.broker_session import BrokerSession
    from core.domain.interfaces.i_broker import IBroker
    from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository

_log = logging.getLogger(__name__)


class BrokerSessionManager(IBrokerSessionManager):
    """Concrete session manager using IBroker + IBrokerSessionRepository."""

    def __init__(
        self,
        broker: IBroker,
        session_repository: IBrokerSessionRepository,
    ) -> None:
        self._broker = broker
        self._session_repo = session_repository

    async def create_session(
        self,
        api_key: str,
        request_token: str,
        api_secret: str,
    ) -> BrokerSession:
        await self._session_repo.deactivate_all(self._broker.broker_name)
        session = await self._broker.login(
            api_key=api_key,
            request_token=request_token,
            api_secret=api_secret,
        )
        # Fetch profile to store authenticated user name
        try:
            profile = await self._broker.get_profile(session)
            session.user_name = profile.full_name or profile.user_id or ""
        except Exception:
            _log.warning("broker_session.create_session: could not fetch profile for user_name")
        await self._session_repo.save(session)
        _log.info(
            "broker_session.created broker=%s session=%s user=%s",
            self._broker.broker_name,
            session.session_id,
            session.user_name,
        )
        return session

    async def refresh_session(self, session: BrokerSession) -> BrokerSession:
        """Re-authenticate; caller must supply new request_token via create_session."""
        _log.warning(
            "broker_session.refresh_requested broker=%s old_session=%s",
            self._broker.broker_name,
            session.session_id,
        )
        session.deactivate()
        await self._session_repo.save(session)
        # refresh requires the caller to start a new auth flow externally;
        # this method deactivates the old session and returns it so the
        # caller knows to prompt for a new request_token.
        return session

    async def validate_session(self, session: BrokerSession) -> bool:
        if not session.is_active or session.is_expired():
            return False
        try:
            await self._broker.get_profile(session)
            return True
        except Exception:
            _log.warning(
                "broker_session.validate.probe_failed session=%s", session.session_id
            )
            return False

    async def terminate_session(self, session: BrokerSession) -> None:
        try:
            await self._broker.logout(session)
        except Exception:
            _log.warning(
                "broker_session.terminate.logout_failed session=%s — deactivating anyway",
                session.session_id,
            )
            session.deactivate()
        await self._session_repo.save(session)
        _log.info(
            "broker_session.terminated broker=%s session=%s",
            self._broker.broker_name,
            session.session_id,
        )
