"""Pydantic schemas for instrument master API responses.

Presentation-layer only. Domain entities are never returned directly.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InstrumentResponse(BaseModel):
    """Single instrument detail returned by lookup endpoints."""

    token: int
    tradingsymbol: str
    exchange: str
    name: str
    segment: str
    instrument_type: str
    asset_type: str
    lot_size: int
    tick_size: Decimal
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: str | None = None
    underlying_symbol: str | None = None
    isin: str | None = None
    is_active: bool


class SyncStatusResponse(BaseModel):
    """Result of a sync operation."""

    status: str
    instruments_added: int
    instruments_updated: int
    instruments_deactivated: int
    lot_size_changes_count: int
    duration_ms: int
    error_detail: str = ""


class InstrumentHealthResponse(BaseModel):
    """Health snapshot for the instrument master."""

    instrument_count: int
    last_sync_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the last successful sync. Null if no sync has run.",
    )
    sync_status: str = Field(
        description="Last sync status: SUCCESS, PARTIAL, FAILED, or UNKNOWN."
    )
    provider_name: str = "kite"
