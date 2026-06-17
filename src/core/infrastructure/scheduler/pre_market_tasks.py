"""PreMarketScheduler — APScheduler cron jobs that run before market open.

Schedule (all times IST = UTC+5:30):
  07:30  Download instrument master from broker
  07:40  Diff and validate new data
  07:50  Rebuild Redis cache
  07:55  Publish InstrumentMasterRefreshed event

The scheduler is driven by InstrumentMasterService.refresh() which
encapsulates all four steps in a single atomic operation. The individual
time slots are advisory; if refresh() completes early, all steps are done.

Reference: docs/13_INSTRUMENT_MASTER.md §Daily Refresh Schedule
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from core.domain.interfaces.i_instrument_master import IInstrumentMasterService

logger = get_logger(__name__)

# 07:30 IST = 02:00 UTC
_REFRESH_HOUR_UTC = 2
_REFRESH_MINUTE_UTC = 0
_IST_TIMEZONE = "Asia/Kolkata"


class PreMarketScheduler:
    """Manages APScheduler cron jobs for pre-market data tasks.

    Usage (in lifespan):
        scheduler = PreMarketScheduler(instrument_master_service)
        scheduler.start()
        yield
        scheduler.stop()
    """

    def __init__(self, instrument_master_service: IInstrumentMasterService) -> None:
        self._service = instrument_master_service
        self._scheduler = AsyncIOScheduler(timezone=_IST_TIMEZONE)
        self._register_jobs()

    def _register_jobs(self) -> None:
        """Register all pre-market cron triggers."""
        self._scheduler.add_job(
            self._run_instrument_refresh,
            trigger=CronTrigger(
                hour=7,
                minute=30,
                timezone=_IST_TIMEZONE,
            ),
            id="instrument_master_refresh",
            name="Instrument Master Daily Refresh (07:30 IST)",
            replace_existing=True,
            misfire_grace_time=300,
        )

    def start(self) -> None:
        self._scheduler.start()
        logger.info("pre_market_scheduler.started")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("pre_market_scheduler.stopped")

    async def _run_instrument_refresh(self) -> None:
        logger.info("pre_market_scheduler.instrument_refresh.triggered")
        try:
            result = await self._service.refresh()
            logger.info(
                "pre_market_scheduler.instrument_refresh.done",
                status=result.status,
                added=result.instruments_added,
                updated=result.instruments_updated,
                deactivated=result.instruments_deactivated,
                lot_size_changes=result.has_lot_size_changes,
            )
        except Exception:
            logger.exception("pre_market_scheduler.instrument_refresh.error")
