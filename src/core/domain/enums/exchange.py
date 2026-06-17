"""Exchange enumeration for all supported trading venues.

Reference: docs/13_INSTRUMENT_MASTER.md §Enumerations
"""

from __future__ import annotations

from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"
    CDS = "CDS"
