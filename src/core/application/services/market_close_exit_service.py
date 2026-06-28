"""MarketCloseExitService — enforces intraday discipline by expiring all open
signals at the configured cutoff time (default 15:20 IST).

No option positions are carried overnight. At cutoff:
  - Signals in RISK_APPROVED or RISK_PENDING state → EXPIRED
  - SignalExpired events published for each (pipeline handler routes accordingly)
  - AUTOMATIC mode: downstream exit orders placed via existing OMS flow
  - MANUAL mode: user sees EXPIRED status — acts as exit alert

Polls every 30 seconds. Fires once per calendar day and resets at midnight.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.enums.signal_state import SignalState
from core.domain.events.signal_events import SignalExpired
from core.infrastructure.database.models.signal_models import SignalOrm

if TYPE_CHECKING:
    from core.infrastructure.config.signal_config import SignalConfig
    from core.infrastructure.events.redis_event_bus import RedisStreamEventBus

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")
_POLL_SECONDS = 30

# States that represent an open intraday position that must not be carried overnight
_OPEN_STATES = frozenset({
    SignalState.RISK_APPROVED.value,
    SignalState.RISK_PENDING.value,
})


class MarketCloseExitService:
    """Background service — expires all open intraday signals at market cutoff."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: "RedisStreamEventBus",
        signal_config: "SignalConfig | None" = None,
        poll_interval_seconds: int = _POLL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._poll_interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._cutoff_fired_date: str | None = None  # YYYY-MM-DD — prevents double-fire per day

        cutoff_str = "15:20:00"
        if signal_config is not None:
            cutoff_str = signal_config.intraday_risk.cutoff_time
        self._cutoff: time = time.fromisoformat(cutoff_str)

    async def start(self) -> None:
        _log.info("market_close_exit.started cutoff_ist=%s", self._cutoff)
        while not self._stop_event.is_set():
            try:
                await self._check_and_fire()
            except Exception:
                _log.exception("market_close_exit.check_error")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=float(self._poll_interval)
                )
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop_event.set()
        _log.info("market_close_exit.stop_requested")

    async def _check_and_fire(self) -> None:
        now_ist = datetime.now(_IST)
        today_str = now_ist.strftime("%Y-%m-%d")

        # Reset fired flag at midnight (new trading day)
        if self._cutoff_fired_date and self._cutoff_fired_date != today_str:
            self._cutoff_fired_date = None

        if now_ist.time() < self._cutoff:
            return
        if self._cutoff_fired_date == today_str:
            return  # already fired today

        count = await self._expire_open_signals()
        self._cutoff_fired_date = today_str
        log_fn = _log.warning if count > 0 else _log.info
        log_fn(
            "market_close_exit.cutoff_fired ist=%s expired_signals=%d — "
            "no intraday carry-over",
            now_ist.strftime("%H:%M:%S IST"), count,
        )

    async def _expire_open_signals(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOrm).where(SignalOrm.state.in_(_OPEN_STATES))
            )
            signals = result.scalars().all()
            if not signals:
                return 0

            signal_ids = [s.signal_id for s in signals]
            await session.execute(
                update(SignalOrm)
                .where(SignalOrm.signal_id.in_(signal_ids))
                .values(state=SignalState.EXPIRED.value)
            )
            await session.commit()

        for signal_id in signal_ids:
            await self._event_bus.publish(SignalExpired(signal_id=signal_id))
            _log.info("market_close_exit.signal_expired signal_id=%s", signal_id)

        return len(signal_ids)
