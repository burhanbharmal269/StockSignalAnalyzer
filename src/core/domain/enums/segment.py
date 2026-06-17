"""Segment enumeration for instrument market segments.

Reference: docs/13_INSTRUMENT_MASTER.md §Enumerations
"""

from __future__ import annotations

from enum import StrEnum


class Segment(StrEnum):
    NSE_EQ = "NSE_EQ"
    BSE_EQ = "BSE_EQ"
    NSE_FO = "NSE_FO"
    BSE_FO = "BSE_FO"
    MCX_FO = "MCX_FO"
    CDS_FO = "CDS_FO"
