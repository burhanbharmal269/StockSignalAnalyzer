"""InstrumentRefreshResult — outcome of a single instrument master refresh cycle.

Reference: docs/13_INSTRUMENT_MASTER.md §Refresh Lifecycle
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RefreshStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class LotSizeChange:
    """Records a single lot size change detected during refresh."""

    token: int
    tradingsymbol: str
    old_lot_size: int
    new_lot_size: int


@dataclass(frozen=True)
class InstrumentRefreshResult:
    """Immutable outcome record for one instrument master refresh run."""

    status: RefreshStatus
    instruments_added: int
    instruments_updated: int
    instruments_deactivated: int
    duration_ms: int
    lot_size_changes: list[LotSizeChange] = field(default_factory=list)
    error_detail: str = ""

    @property
    def total_processed(self) -> int:
        return self.instruments_added + self.instruments_updated

    @property
    def has_lot_size_changes(self) -> bool:
        return len(self.lot_size_changes) > 0
