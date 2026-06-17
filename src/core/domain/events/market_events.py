"""Market data domain events published by infrastructure data services.

CandleClosedEvent  — emitted by CandleAggregatorService on interval boundary.
OptionChainUpdatedEvent — emitted by OptionChainPoller every 60 seconds.

Reference: docs/11_EVENT_BUS_ARCHITECTURE.md, docs/12_WEBSOCKET_MANAGER.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.events.base import DomainEvent


@dataclass(frozen=True)
class CandleClosedEvent(DomainEvent):
    """A completed OHLCV bar published when an interval boundary is crossed.

    Consumed by:
        - FeatureEngineeringService (Phase 9) to compute indicators
        - CandleRepository to persist to TimescaleDB
    """

    instrument_token: int = 0
    tradingsymbol: str = ""
    exchange: str = ""
    interval: str = ""
    open: Decimal = field(default_factory=lambda: Decimal("0"))
    high: Decimal = field(default_factory=lambda: Decimal("0"))
    low: Decimal = field(default_factory=lambda: Decimal("0"))
    close: Decimal = field(default_factory=lambda: Decimal("0"))
    volume: int = 0
    open_interest: int | None = None
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class OptionChainUpdatedEvent(DomainEvent):
    """Signals that a new option chain snapshot is available.

    Consumed by:
        - FeatureEngineeringService (Phase 9) for PCR, Max Pain, GEX
        - OptionChainRepository to persist snapshot

    ``entry_count`` is the number of strike entries in the snapshot.
    Full data is written directly to the DB/cache by the poller;
    consumers re-read from there rather than receiving it in the event.
    """

    symbol: str = ""
    expiry_date: str = ""
    entry_count: int = 0
    pcr: Decimal = field(default_factory=lambda: Decimal("0"))
