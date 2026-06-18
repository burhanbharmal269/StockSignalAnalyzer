"""Pydantic schemas for signal endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SignalResponse(BaseModel):
    signal_id: str
    symbol: str
    exchange: str
    signal_type: str
    strategy_type: str
    asset_type: str
    regime: str
    state: str
    confidence: float | None
    adjusted_score: float | None
    raw_score: float | None
    valid_until: datetime
    correlation_id: str
    risk_rejection_reason: str
    risk_profile_id: str | None
    allocation_id: str | None
    portfolio_id: str | None
    capital_source_mode: str | None
    created_at: datetime
    entry_price: float | None
    stop_loss_price: float | None
    target_price: float | None
    # Option contract recommendation
    option_type: str | None = None
    option_strike: float | None = None
    option_expiry: str | None = None
    option_symbol: str | None = None
    option_entry: float | None = None
    option_sl: float | None = None
    option_target: float | None = None


class SignalListResponse(BaseModel):
    signals: list[SignalResponse]
    total: int


class RejectSignalRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
