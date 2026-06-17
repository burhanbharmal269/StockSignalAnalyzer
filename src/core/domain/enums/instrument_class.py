"""InstrumentClass enumeration for confidence engine classification.

Used by the Confidence Engine win-rate lookup and signal_performance_stats
table to segment historical accuracy by instrument type.

Reference: docs/21_SIGNAL_ENGINE.md §Stage 3, docs/18_TIMESCALEDB_ARCHITECTURE.md
"""

from __future__ import annotations

from enum import StrEnum


class InstrumentClass(StrEnum):
    INDEX_OPTION = "INDEX_OPTION"
    INDEX_FUTURE = "INDEX_FUTURE"
    STOCK_OPTION = "STOCK_OPTION"
    STOCK_FUTURE = "STOCK_FUTURE"
