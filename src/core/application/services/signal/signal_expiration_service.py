"""SignalExpirationService — background TTL enforcement for active signals.

Handles two states:
  FORWARDED → EXPIRED  (signal sent to OMS, never executed within TTL)
  RISK_APPROVED → FAILED  (signal approved but never picked up by OMS within TTL)

Persistence-first invariant: signal is persisted before any event is published.
Once expired/failed the signal is in a terminal state — OMS must not process it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from core.domain.enums.signal_state import SignalState
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_signal_cache_repository import ISignalCacheRepository
from core.domain.interfaces.i_signal_repository import ISignalRepository

_log = logging.getLogger(__name__)

_TTL_EXPIRED_REASON = "ttl_expired_before_oms_pickup"


class SignalExpirationService:
    """Periodically terminates stale signals past their valid_until timestamp.

    Intended to be called by a scheduler every minute during market hours.

    FORWARDED signals:  expire() → EXPIRED (terminal)
    RISK_APPROVED signals: fail() → FAILED (terminal)
        These were never forwarded to OMS. Marking them FAILED prevents OMS
        from picking them up after their TTL has lapsed.
    """

    def __init__(
        self,
        signal_repository: ISignalRepository,
        signal_cache: ISignalCacheRepository,
        event_bus: IEventBus,
    ) -> None:
        self._repo = signal_repository
        self._cache = signal_cache
        self._event_bus = event_bus

    async def expire_stale(self) -> int:
        """Terminate all stale signals in FORWARDED or RISK_APPROVED state.

        Returns:
            Total number of signals terminated in this run.
        """
        now = datetime.now(UTC)
        terminated = 0
        terminated += await self._expire_forwarded(now)
        terminated += await self._fail_risk_approved(now)
        if terminated:
            _log.info("Expiration sweep: %d signal(s) terminated", terminated)
        return terminated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _expire_forwarded(self, now: datetime) -> int:
        """FORWARDED → EXPIRED for signals past their TTL."""
        forwarded = await self._repo.get_by_state(SignalState.FORWARDED)
        count = 0
        for signal in forwarded:
            if signal.valid_until > now:
                continue
            try:
                signal.expire()
                await self._repo.save(signal)
                events = signal.pull_events()
                for event in events:
                    await self._event_bus.publish(event)
                count += 1
                _log.info(
                    "Signal EXPIRED (was FORWARDED): signal_id=%s valid_until=%s",
                    signal.signal_id,
                    signal.valid_until,
                )
            except Exception:
                _log.exception(
                    "Failed to expire FORWARDED signal %s — will retry next cycle",
                    signal.signal_id,
                )
        return count

    async def _fail_risk_approved(self, now: datetime) -> int:
        """RISK_APPROVED → FAILED for signals OMS never picked up within TTL.

        RISK_APPROVED → EXPIRED is not in the state machine, so we use FAILED
        with a descriptive reason to prevent OMS from processing stale approvals.
        """
        approved = await self._repo.get_by_state(SignalState.RISK_APPROVED)
        count = 0
        for signal in approved:
            if signal.valid_until > now:
                continue
            try:
                signal.fail(reason=_TTL_EXPIRED_REASON)
                await self._repo.save(signal)
                events = signal.pull_events()
                for event in events:
                    await self._event_bus.publish(event)
                count += 1
                _log.warning(
                    "Signal FAILED (RISK_APPROVED expired before OMS pickup): "
                    "signal_id=%s valid_until=%s",
                    signal.signal_id,
                    signal.valid_until,
                )
            except Exception:
                _log.exception(
                    "Failed to terminate RISK_APPROVED signal %s — will retry next cycle",
                    signal.signal_id,
                )
        return count
