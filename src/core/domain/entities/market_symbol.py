"""MarketSymbol — canonical representation of a tradeable instrument."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MarketSymbol:
    symbol: str
    name: str = ""
    exchange: str = "NSE"
    segment: str = "EQ"       # EQ | FUT | OPT | IDX | ETF
    sector: str | None = None
    industry: str | None = None
    is_fo: bool = False
    is_index: bool = False
    is_active: bool = True
    lot_size: int = 1
    instrument_token: int | None = None
    isin: str | None = None
    meta: dict = field(default_factory=dict)
    added_at: datetime | None = None
    updated_at: datetime | None = None
