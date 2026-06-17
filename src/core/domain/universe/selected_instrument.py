"""SelectedInstrument — output value object from the Universe Selection Engine.

Represents one instrument in the bounded candidate list forwarded to
Feature Engineering after the 8-stage filter pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class SelectedInstrument:
    """One instrument in the universe selected candidate list.

    Attributes:
        instrument_token:   Unique Kite numeric token.
        underlying:         Underlying symbol (e.g. "NIFTY").
        instrument_class:   "OPTION" | "FUTURE".
        expiry_date:        Contract expiry date.
        sector:             NSE sector for observability.
        composite_score:    Weighted ranking score (0.0 for protected instruments).
        rank:               1-indexed rank within the selected set (1 = highest priority).
        protected:          True if included due to active position protection.
        filter_metadata:    Stage-by-stage pass/fail record for observability.
    """

    instrument_token: int
    underlying: str
    instrument_class: str
    expiry_date: date
    sector: str
    composite_score: float
    rank: int
    protected: bool = False
    filter_metadata: dict[str, Any] = field(default_factory=dict)
