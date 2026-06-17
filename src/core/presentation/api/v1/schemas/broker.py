"""Pydantic schemas for broker endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KillSwitchStateResponse(BaseModel):
    is_active: bool
    activated_at: datetime | None
    activated_by: str | None
    activation_reason: str | None
    deactivated_at: datetime | None
    deactivated_by: str | None


class BrokerStatusResponse(BaseModel):
    broker_name: str
    status: str
    # Session connection state: CONNECTED | DISCONNECTED | AUTH_REQUIRED | SESSION_EXPIRED | ERROR
    session_status: str
    kill_switch: KillSwitchStateResponse
    latency_ms: float
    details: dict
    checked_at: datetime
    # Authenticated user (populated when session is live and valid)
    authenticated_user: str | None
    session_expires_at: datetime | None
    session_created_at: datetime | None
    # Per-capability status: OK | DEGRADED | UNAVAILABLE
    market_data_status: str
    order_placement_status: str
    historical_data_status: str


class TradingModeResponse(BaseModel):
    mode: str


class KillSwitchActivateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class KillSwitchDeactivateRequest(BaseModel):
    note: str = Field(min_length=1, max_length=500)
    override_loss_check: bool = False


class BrokerLoginUrlResponse(BaseModel):
    login_url: str
    mode: str


class BrokerSessionResponse(BaseModel):
    session_id: uuid.UUID
    broker_name: str
    is_active: bool
    is_expired: bool
    expires_at: datetime
    created_at: datetime
    user_name: str


class BrokerSessionStatusResponse(BaseModel):
    """Returned by GET /broker/session — null session means not logged in."""
    mode: str
    session: BrokerSessionResponse | None
