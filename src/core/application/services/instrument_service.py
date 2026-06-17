"""InstrumentService — application-layer façade for instrument operations.

Thin orchestrator that delegates to the appropriate use case. Routes and
DI containers depend on this service; they never call use cases directly.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md §CLEAN ARCHITECTURE RULES
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.entities.instrument import Instrument
from core.domain.value_objects.instrument_health import InstrumentHealth
from core.domain.value_objects.instrument_refresh_result import InstrumentRefreshResult

if TYPE_CHECKING:
    from core.application.use_cases.instrument_lookup_use_case import (
        InstrumentLookupUseCase,
    )
    from core.application.use_cases.instrument_sync_use_case import InstrumentSyncUseCase


class InstrumentService:
    """Façade exposing instrument sync and lookup to the presentation layer."""

    def __init__(
        self,
        sync_use_case: InstrumentSyncUseCase,
        lookup_use_case: InstrumentLookupUseCase,
    ) -> None:
        self._sync = sync_use_case
        self._lookup = lookup_use_case

    async def sync(self, *, full: bool = True) -> InstrumentRefreshResult:
        """Trigger a sync cycle (full or incremental)."""
        return await self._sync.execute(full=full)

    async def get_by_token(self, token: int) -> Instrument:
        """Lookup instrument by broker token. Raises KeyError if not found."""
        return await self._lookup.get_by_token(token)

    async def get_by_symbol(self, exchange: str, tradingsymbol: str) -> Instrument:
        """Lookup instrument by exchange + symbol. Raises KeyError if not found."""
        return await self._lookup.get_by_symbol(exchange, tradingsymbol)

    async def count_active(self) -> int:
        """Return total active instrument count."""
        return await self._lookup.count_active()

    async def get_health(self) -> InstrumentHealth:
        """Return operational health snapshot."""
        return await self._lookup.get_health()
