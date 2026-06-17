"""InstrumentLookupUseCase — instrument queries and health reporting.

Application-layer use case. Delegates to IInstrumentMasterService for
cache-backed lookups and to IInstrumentRepository for counts.

Reference: docs/13_INSTRUMENT_MASTER.md §Instrument Master Service Interface
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.domain.entities.instrument import Instrument
from core.domain.value_objects.instrument_health import InstrumentHealth
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.domain.interfaces.i_instrument_master import IInstrumentMasterService
    from core.domain.interfaces.i_instrument_repository import IInstrumentRepository

logger = get_logger(__name__)

_REDIS_LAST_SYNC_KEY = "instrument:last_sync_at"
_REDIS_SYNC_STATUS_KEY = "instrument:sync_status"


class InstrumentLookupUseCase:
    """Handles instrument lookup queries and health reporting.

    Injects:
        instrument_master — IInstrumentMasterService (cache-backed queries)
        instrument_repo   — IInstrumentRepository (count queries bypass cache)
        redis_client      — reads sync metadata written by InstrumentSyncUseCase
    """

    def __init__(
        self,
        instrument_master: IInstrumentMasterService,
        instrument_repo: IInstrumentRepository,
        redis_client: Redis,  # type: ignore[type-arg]
    ) -> None:
        self._master = instrument_master
        self._repo = instrument_repo
        self._redis = redis_client

    async def get_by_token(self, token: int) -> Instrument:
        """Return an instrument by broker token.

        Raises:
            KeyError: If the token is not found.
        """
        return await self._master.get_by_token(token)

    async def get_by_symbol(self, exchange: str, tradingsymbol: str) -> Instrument:
        """Return an instrument by exchange + trading symbol (case-insensitive).

        Raises:
            KeyError: If not found.
        """
        return await self._master.get_by_symbol(exchange, tradingsymbol)

    async def count_active(self) -> int:
        """Return the total number of active instruments in the DB."""
        return await self._repo.count_active()

    async def get_health(self) -> InstrumentHealth:
        """Return a health snapshot for the instrument master.

        Reads last_sync_at and sync_status from Redis (set by sync use case).
        Falls back to defaults when no sync has been run yet.
        """
        instrument_count = await self._repo.count_active()

        last_sync_at: datetime | None = None
        sync_status = "UNKNOWN"

        try:
            raw_ts: str | None = await self._redis.get(_REDIS_LAST_SYNC_KEY)
            raw_status: str | None = await self._redis.get(_REDIS_SYNC_STATUS_KEY)

            if raw_ts:
                last_sync_at = datetime.fromisoformat(raw_ts)
            if raw_status:
                sync_status = raw_status
        except Exception:
            logger.warning("instrument_lookup.health.redis_read_failed")

        return InstrumentHealth(
            instrument_count=instrument_count,
            last_sync_at=last_sync_at,
            sync_status=sync_status,
        )
