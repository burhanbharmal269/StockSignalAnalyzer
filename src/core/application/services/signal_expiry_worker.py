"""SignalExpiryWorker — background service that expires stale signals.

Polls signals every 60 seconds. Any signal in an active state whose
valid_until timestamp has passed is transitioned to EXPIRED and a
SignalExpired domain event is published.

Runs as a standalone async task started at application startup.
Reference: docs/21_SIGNAL_ENGINE.md §Signal TTL & Expiry
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.enums.signal_state import SignalState
from core.domain.events.signal_events import SignalExpired
from core.infrastructure.database.models.signal_models import SignalOrm

if TYPE_CHECKING:
    from core.infrastructure.events.redis_event_bus import RedisStreamEventBus

_log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60

_EXPIRABLE_STATES = {
    SignalState.SCORING.value,
    SignalState.SCORED.value,
    SignalState.RISK_PENDING.value,
    SignalState.RISK_APPROVED.value,
}


class SignalExpiryWorker:
    """Polls the signals table and expires TTL-elapsed records."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: RedisStreamEventBus,
        poll_interval_seconds: int = _POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Run the expiry loop until stop() is called."""
        _log.info("SignalExpiryWorker started, poll_interval=%ds", self._poll_interval)
        while not self._stop_event.is_set():
            try:
                await self._expire_stale_signals()
            except Exception:
                _log.exception("SignalExpiryWorker encountered an error")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=float(self._poll_interval)
                )
            except TimeoutError:
                pass

    async def stop(self) -> None:
        """Signal the loop to exit after the current iteration."""
        self._stop_event.set()
        _log.info("SignalExpiryWorker stop requested")

    async def _expire_stale_signals(self) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm).where(
                    and_(
                        SignalOrm.state.in_(_EXPIRABLE_STATES),
                        SignalOrm.valid_until < now,
                    )
                )
            )
            stale = result.scalars().all()

            if not stale:
                return

            signal_ids = [row.signal_id for row in stale]
            await session.execute(
                update(SignalOrm)
                .where(SignalOrm.signal_id.in_(signal_ids))
                .values(state=SignalState.EXPIRED.value)
            )
            await session.commit()

        for signal_id in signal_ids:
            await self._event_bus.publish(SignalExpired(signal_id=signal_id))
            _log.debug("signal expired signal_id=%s", signal_id)

        _log.info("SignalExpiryWorker expired %d signals", len(signal_ids))
