"""InstrumentHealth — snapshot of the instrument master's operational state.

Returned by InstrumentLookupUseCase.get_health() and exposed via the
/api/v1/instruments/health endpoint.

Reference: docs/13_INSTRUMENT_MASTER.md §Observability
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InstrumentHealth:
    """Operational health snapshot for the instrument master."""

    instrument_count: int
    last_sync_at: datetime | None
    sync_status: str
    provider_name: str = "kite"
