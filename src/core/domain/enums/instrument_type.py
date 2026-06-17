"""InstrumentType enumeration for tradable instrument categories.

Reference: docs/13_INSTRUMENT_MASTER.md §Enumerations
"""

from __future__ import annotations

from enum import StrEnum


class InstrumentType(StrEnum):
    EQ = "EQ"
    FUT = "FUT"
    CE = "CE"
    PE = "PE"
    INDEX = "INDEX"
