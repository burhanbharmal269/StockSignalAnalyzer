"""Execution analytics and paper trading validation router.

GET /api/v1/analytics/execution/summary    — aggregate execution stats
GET /api/v1/analytics/execution/records    — individual fill records
GET /api/v1/paper-trading/reports/{type}  — list period reports (DAILY/WEEKLY/MONTHLY)
GET /api/v1/paper-trading/reports/{type}/{label} — single period report
POST /api/v1/paper-trading/snapshot       — trigger manual snapshot
"""


from datetime import datetime

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.execution_analytics_service import ExecutionAnalyticsService
from core.application.services.paper_trading_validation_service import (
    PaperTradingValidationService,
)
from core.presentation.api.v1.dependencies.auth import require_authenticated, require_admin
from core.presentation.api.v1.schemas.auth import CurrentUser
from pydantic import BaseModel
from typing import Any

router = APIRouter(tags=["Analytics"])


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class ExecutionSummaryResponse(BaseModel):
    symbol: str | None
    broker_name: str | None
    period_start: datetime | None
    period_end: datetime | None
    record_count: int
    avg_broker_submit_latency_ms: float | None
    avg_fill_latency_ms: float | None
    avg_e2e_latency_ms: float | None
    avg_slippage_bps: float | None
    avg_hold_seconds: float | None
    total_pnl: float | None
    win_count: int
    loss_count: int
    win_rate: float


class ExecutionRecordResponse(BaseModel):
    analytics_id: int
    broker_name: str
    symbol: str
    broker_submit_latency_ms: float | None
    fill_latency_ms: float | None
    total_e2e_latency_ms: float | None
    slippage_bps: float | None
    hold_seconds: float | None
    realized_pnl: float | None
    trading_mode: str
    recorded_at: datetime


class ExecutionRecordsListResponse(BaseModel):
    records: list[ExecutionRecordResponse]
    total: int


# --------------------------------------------------------------------------
# Execution analytics endpoints
# --------------------------------------------------------------------------


@router.get(
    "/api/v1/analytics/execution/summary",
    response_model=ExecutionSummaryResponse,
    summary="Aggregate execution analytics",
)
@inject
async def get_execution_summary(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    symbol: str | None = Query(default=None),
    broker_name: str | None = Query(default=None),
    trading_mode: str | None = Query(default=None),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    analytics_service: ExecutionAnalyticsService = Depends(  # noqa: B008
        Provide[ApplicationContainer.execution_analytics_service]
    ),
) -> ExecutionSummaryResponse:
    summary = await analytics_service.get_summary(
        since=since, until=until, symbol=symbol,
        broker_name=broker_name, trading_mode=trading_mode,
    )
    total = summary.win_count + summary.loss_count
    return ExecutionSummaryResponse(
        symbol=summary.symbol,
        broker_name=summary.broker_name,
        period_start=summary.period_start,
        period_end=summary.period_end,
        record_count=summary.record_count,
        avg_broker_submit_latency_ms=_f(summary.avg_broker_submit_latency_ms),
        avg_fill_latency_ms=_f(summary.avg_fill_latency_ms),
        avg_e2e_latency_ms=_f(summary.avg_e2e_latency_ms),
        avg_slippage_bps=_f(summary.avg_slippage_bps),
        avg_hold_seconds=_f(summary.avg_hold_seconds),
        total_pnl=_f(summary.total_pnl),
        win_count=summary.win_count,
        loss_count=summary.loss_count,
        win_rate=round(summary.win_count / total, 4) if total else 0.0,
    )


@router.get(
    "/api/v1/analytics/execution/records",
    response_model=ExecutionRecordsListResponse,
    summary="List individual execution analytics records",
)
@inject
async def list_execution_records(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    analytics_service: ExecutionAnalyticsService = Depends(  # noqa: B008
        Provide[ApplicationContainer.execution_analytics_service]
    ),
) -> ExecutionRecordsListResponse:
    records = await analytics_service.list_records(
        since=since, until=until, symbol=symbol, limit=limit, offset=offset
    )
    return ExecutionRecordsListResponse(
        records=[
            ExecutionRecordResponse(
                analytics_id=r.analytics_id,
                broker_name=r.broker_name,
                symbol=r.symbol,
                broker_submit_latency_ms=_f(r.broker_submit_latency_ms),
                fill_latency_ms=_f(r.fill_latency_ms),
                total_e2e_latency_ms=_f(r.total_e2e_latency_ms),
                slippage_bps=_f(r.slippage_bps),
                hold_seconds=_f(r.hold_seconds),
                realized_pnl=_f(r.realized_pnl),
                trading_mode=r.trading_mode,
                recorded_at=r.recorded_at,
            )
            for r in records
        ],
        total=len(records),
    )


# --------------------------------------------------------------------------
# Paper trading validation endpoints
# --------------------------------------------------------------------------


@router.get(
    "/api/v1/paper-trading/reports/{period_type}",
    summary="List paper trading reports for a period type (DAILY/WEEKLY/MONTHLY)",
)
@inject
async def list_paper_trading_reports(
    period_type: str,
    limit: int = Query(default=30, ge=1, le=366),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    pt_service: PaperTradingValidationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.paper_trading_validation_service]
    ),
) -> dict:
    period_type = period_type.upper()
    if period_type not in ("DAILY", "WEEKLY", "MONTHLY"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="period_type must be DAILY, WEEKLY, or MONTHLY")
    reports = await pt_service.list_reports(period_type, limit=limit, offset=offset)
    return {"period_type": period_type, "reports": reports, "count": len(reports)}


@router.get(
    "/api/v1/paper-trading/reports/{period_type}/{period_label}",
    summary="Get a specific paper trading report",
)
@inject
async def get_paper_trading_report(
    period_type: str,
    period_label: str,
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    pt_service: PaperTradingValidationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.paper_trading_validation_service]
    ),
) -> dict:
    return await pt_service.get_report(period_type.upper(), period_label)


@router.post(
    "/api/v1/paper-trading/snapshot",
    summary="Trigger paper trading snapshot (admin only)",
)
@inject
async def trigger_snapshot(
    period_type: str = Query(default="DAILY"),
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    pt_service: PaperTradingValidationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.paper_trading_validation_service]
    ),
) -> dict:
    period_type = period_type.upper()
    if period_type == "DAILY":
        snap = await pt_service.snapshot_daily()
    elif period_type == "WEEKLY":
        snap = await pt_service.snapshot_weekly()
    elif period_type == "MONTHLY":
        snap = await pt_service.snapshot_monthly()
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid period_type")
    return {
        "message": "Snapshot created",
        "period_type": snap.period_type,
        "period_label": snap.period_label,
        "signals_generated": snap.signals_generated,
        "orders_placed": snap.orders_placed,
        "gross_pnl": float(snap.gross_pnl),
    }


def _f(v) -> float | None:
    return float(v) if v is not None else None
