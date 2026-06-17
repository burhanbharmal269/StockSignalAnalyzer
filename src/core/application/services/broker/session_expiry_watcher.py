"""SessionExpiryWatcher — detects expired Kite sessions and activates kill switch.

Kite access tokens expire daily at 06:00 IST. This watcher:
  - Runs at startup: validates any stored session, deactivates if expired.
  - Runs every 60s: detects the moment a session crosses its expiry time.
  - On expiry: deactivates session in DB, activates kill switch, logs audit event.

Paper mode is exempt — paper sessions never expire.

Reference: Security Constraint — LIVE MODE + INVALID SESSION must never be allowed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.kill_switch_service import KillSwitchService
    from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository
    from core.infrastructure.config.broker_config import BrokerConfig

_log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60


class SessionExpiryWatcher:
    """Background service that watches for Kite session expiry and activates the kill switch."""

    def __init__(
        self,
        session_repository: IBrokerSessionRepository,
        kill_switch_service: KillSwitchService,
        broker_config: BrokerConfig,
    ) -> None:
        self._session_repo = session_repository
        self._kill_switch = kill_switch_service
        self._config = broker_config

    async def startup_validate(self) -> None:
        """Called at application startup.

        Validates any stored active session. If in live mode with an expired
        session: deactivates the session and activates the kill switch so the
        platform fails closed (no live orders possible until re-authentication).
        """
        if not self._config.is_live_mode:
            _log.info("session_expiry_watcher.startup: paper mode — session validation skipped")
            return

        session = await self._session_repo.get_active("kite")

        if session is None:
            _log.warning(
                "session_expiry_watcher.startup: live mode but no active kite session found "
                "— authentication required before trading"
            )
            return

        if session.is_expired():
            _log.critical(
                "session_expiry_watcher.startup: kite session is EXPIRED (expires_at=%s) "
                "— deactivating session, re-authentication required",
                session.expires_at,
            )
            session.deactivate()
            await self._session_repo.save(session)
        else:
            _log.info(
                "session_expiry_watcher.startup: kite session valid for user=%s, expires_at=%s",
                session.user_name or "unknown",
                session.expires_at,
            )

    async def run(self) -> None:
        """Background loop — checks session expiry every 60 seconds."""
        _log.info("session_expiry_watcher.started interval=%ds", _CHECK_INTERVAL_SECONDS)
        while True:
            try:
                await self._check_expiry()
            except Exception:
                _log.exception("session_expiry_watcher.check_expiry_failed")
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

    async def _check_expiry(self) -> None:
        if not self._config.is_live_mode:
            return

        session = await self._session_repo.get_active("kite")
        if session is None:
            return

        if session.is_expired():
            _log.critical(
                "session_expiry_watcher: kite session expired for user=%s at %s "
                "— deactivating, re-authentication required",
                session.user_name or "unknown",
                session.expires_at,
            )
            session.deactivate()
            await self._session_repo.save(session)
