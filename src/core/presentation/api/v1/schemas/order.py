"""Pydantic schemas for order endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OrderResponse(BaseModel):
    order_id: str
    signal_id: str | None
    tradingsymbol: str
    symbol: str
    exchange: str
    transaction_type: str
    order_type: str
    product: str
    quantity: int
    lots: int
    limit_price: float | None
    trigger_price: float | None
    state: str
    broker_order_id: str
    filled_quantity: int
    average_fill_price: float | None
    rejection_reason: str
    trading_mode: str
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    total: int
