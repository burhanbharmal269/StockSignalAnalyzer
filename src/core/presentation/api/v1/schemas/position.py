"""Pydantic schemas for position endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PositionResponse(BaseModel):
    position_id: str
    signal_id: str | None
    order_id: str | None
    symbol: str
    exchange: str
    direction: str
    quantity: int
    entry_price: float
    current_price: float
    state: str
    realized_pnl: float
    current_mtm_pnl: float
    unrealized_pnl: float
    total_pnl: float
    trading_mode: str
    opened_at: datetime
    closed_at: datetime | None


class PositionListResponse(BaseModel):
    positions: list[PositionResponse]
    total: int


class ClosePositionRequest(BaseModel):
    exit_price: float = Field(gt=0, description="Exit price for the position close")
