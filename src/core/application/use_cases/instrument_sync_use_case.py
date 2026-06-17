"""InstrumentSyncUseCase — orchestrates full and incremental instrument syncs.

Application-layer use case. Calls the IInstrumentMasterService for the
heavy lifting and tracks sync metadata (last sync time, status) in Redis.

Full sync   — downloads every exchange, validates, upserts all rows.
Incremental — only upserts rows whose token is not yet in the DB. Used
              for intraday top-ups (e.g. new contracts listed mid-session).

Reference: docs/13_INSTRUMENT_MASTER.md §Synchronization
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.domain.value_objects.instrument_refresh_result import (
    InstrumentRefreshResult,
    RefreshStatus,
)
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.domain.interfaces.i_instrument_master import IInstrumentMasterService
    from core.domain.interfaces.i_instrument_provider import IInstrumentProvider
    from core.domain.interfaces.i_instrument_repository import IInstrumentRepository
    from core.infrastructure.data.expiry_calendar import ExpiryCalendar

logger = get_logger(__name__)

_REDIS_LAST_SYNC_KEY = "instrument:last_sync_at"
_REDIS_SYNC_STATUS_KEY = "instrument:sync_status"


class InstrumentSyncUseCase:
    """Orchestrates full and incremental instrument master synchronisation.

    Injects:
        instrument_master  — IInstrumentMasterService (provides refresh())
        instrument_provider — IInstrumentProvider (direct access for incremental)
        instrument_repo    — IInstrumentRepository (for token diffing)
        redis_client       — for persisting sync metadata
        expiry_calendar    — for parsing new instruments inline
    """

    def __init__(
        self,
        instrument_master: IInstrumentMasterService,
        instrument_provider: IInstrumentProvider,
        instrument_repo: IInstrumentRepository,
        redis_client: Redis,  # type: ignore[type-arg]
        expiry_calendar: ExpiryCalendar,
        exchanges: list[str] | None = None,
    ) -> None:
        self._master = instrument_master
        self._provider = instrument_provider
        self._repo = instrument_repo
        self._redis = redis_client
        self._calendar = expiry_calendar
        self._exchanges = exchanges or ["NSE", "NFO", "BSE", "BFO", "MCX", "CDS"]

    async def execute(self, *, full: bool = True) -> InstrumentRefreshResult:
        """Run a sync cycle.

        Args:
            full: When True performs a full sync (download + validate + upsert all).
                  When False performs an incremental sync (new tokens only).

        Returns:
            InstrumentRefreshResult with counts, status, and any lot-size changes.
        """
        sync_type = "full" if full else "incremental"
        logger.info("instrument_sync.start", sync_type=sync_type)

        try:
            if full:
                result = await self._master.refresh()
            else:
                result = await self._incremental_sync()
        except Exception as exc:
            logger.exception("instrument_sync.unhandled_error", sync_type=sync_type)
            result = InstrumentRefreshResult(
                status=RefreshStatus.FAILED,
                instruments_added=0,
                instruments_updated=0,
                instruments_deactivated=0,
                duration_ms=0,
                error_detail=str(exc),
            )

        await self._store_sync_metadata(result)
        logger.info(
            "instrument_sync.complete",
            sync_type=sync_type,
            status=result.status,
            added=result.instruments_added,
            updated=result.instruments_updated,
        )
        return result

    # ------------------------------------------------------------------
    # Incremental sync
    # ------------------------------------------------------------------

    async def _incremental_sync(self) -> InstrumentRefreshResult:
        """Download instruments and upsert only rows not already in the DB."""
        import time

        from core.infrastructure.data.instrument_master_service import _parse_instrument
        start_ms = int(time.monotonic() * 1000)
        added = 0

        existing_tokens = await self._repo.get_all_tokens()

        raw_rows: list[dict[str, str]] = []
        for exchange in self._exchanges:
            rows = await self._provider.download_instruments(exchange)
            raw_rows.extend(rows)

        new_instruments = []
        for row in raw_rows:
            if not row.get("instrument_token"):
                continue
            try:
                token = int(row["instrument_token"])
            except (ValueError, KeyError):
                continue
            if token not in existing_tokens:
                parsed = _parse_instrument(row)
                if parsed is not None:
                    new_instruments.append(parsed)

        if new_instruments:
            await self._repo.save_bulk(new_instruments)
            added = len(new_instruments)
            logger.info(
                "instrument_sync.incremental.new_instruments",
                count=added,
            )

        return InstrumentRefreshResult(
            status=RefreshStatus.SUCCESS,
            instruments_added=added,
            instruments_updated=0,
            instruments_deactivated=0,
            duration_ms=int(time.monotonic() * 1000) - start_ms,
        )

    # ------------------------------------------------------------------
    # Sync metadata
    # ------------------------------------------------------------------

    async def _store_sync_metadata(self, result: InstrumentRefreshResult) -> None:
        """Persist last sync time and status to Redis for health checks."""
        try:
            now_iso = datetime.now(UTC).isoformat()
            await self._redis.set(_REDIS_LAST_SYNC_KEY, now_iso)
            await self._redis.set(_REDIS_SYNC_STATUS_KEY, result.status.value)
        except Exception:
            logger.warning("instrument_sync.metadata.write_failed")
