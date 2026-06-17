"""OptionType enumeration for call and put options.

Reference: docs/13_INSTRUMENT_MASTER.md §Enumerations
"""

from __future__ import annotations

from enum import StrEnum


class OptionType(StrEnum):
    CE = "CE"
    PE = "PE"
