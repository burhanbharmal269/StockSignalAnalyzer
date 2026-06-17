"""Pydantic schemas for reconciliation dashboard APIs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReconciliationDiscrepancySchema(BaseModel):
    discrepancy_id: int
    run_id: int
    discrepancy_type: str
    order_id: UUID | None = None
    broker_order_id: str | None = None
    oms_state: str | None = None
    broker_state: str | None = None
    detail: str | None = None
    repair_action: str | None = None
    repaired: bool
    repaired_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationRunSchema(BaseModel):
    run_id: int
    broker_name: str
    trigger: str
    status: str
    orders_checked: int
    positions_checked: int
    fills_checked: int
    discrepancy_count: int
    rogue_count: int
    repaired_count: int
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    discrepancies: list[ReconciliationDiscrepancySchema] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ReconciliationRunListResponse(BaseModel):
    runs: list[ReconciliationRunSchema]
    total: int


class ReconciliationDiscrepancyListResponse(BaseModel):
    discrepancies: list[ReconciliationDiscrepancySchema]
    total: int


class ManualTriggerResponse(BaseModel):
    message: str
    broker_name: str
    orders_checked: int
    positions_checked: int
    discrepancy_count: int
    rogue_count: int
    status: str
