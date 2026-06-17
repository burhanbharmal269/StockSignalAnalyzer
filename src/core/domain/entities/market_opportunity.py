"""MarketOpportunity — ranked trading opportunity from the scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class MarketOpportunity:
    id: int | None
    symbol: str
    opportunity_type: str          # BREAKOUT | MOMENTUM | VOLUME_SPIKE | OI_EXPANSION | ...
    total_score: Decimal
    confidence: Decimal
    direction: str | None = None   # LONG | SHORT
    technical_score: Decimal | None = None
    volume_score: Decimal | None = None
    sentiment_score: Decimal | None = None
    oi_score: Decimal | None = None
    regime_score: Decimal | None = None
    regime: str | None = None
    meta: dict = field(default_factory=dict)
    created_at: datetime | None = None
    expires_at: datetime | None = None
