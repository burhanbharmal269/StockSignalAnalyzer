"""Trade Management Intelligence — API router."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from container import ApplicationContainer
from core.application.services.trade_management_service import TradeManagementService
from core.presentation.api.v1.dependencies.auth import require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1/trade-management", tags=["trade-management"])


@router.get("/summary")
@inject
async def get_summary(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Overall TMI dashboard: capture ratio, profit tiers, classification counts."""
    return await tmi.get_summary(days=days)


@router.get("/profit-tiers")
@inject
async def get_profit_tiers(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Per-signal MFE breakdown for waterfall chart."""
    signals = await tmi.get_profit_tier_details(days=days)
    return {"days": days, "signals": signals}


@router.get("/classifications")
@inject
async def get_classifications(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Trade classification breakdown."""
    summary = await tmi.get_summary(days=days)
    return {
        "days": days,
        "classifications": summary["classifications"],
        "total": summary["total_accepted"],
    }


@router.get("/capture-ratio")
@inject
async def get_capture_ratio(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Capture ratio distribution across settled signals."""
    return {"days": days, **await tmi.get_capture_ratio_distribution(days=days)}


@router.get("/regime-analysis")
@inject
async def get_regime_analysis(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Which market regimes tend to reverse after initial gains."""
    return {"days": days, "regimes": await tmi.get_regime_reversal_analysis(days=days)}


@router.get("/weekly-report")
@inject
async def get_weekly_report(
    days: int = Query(7, ge=1, le=30),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Generate full weekly TMI report and persist it."""
    return await tmi.generate_weekly_report(lookback_days=days)


@router.post("/classify")
@inject
async def run_classification(
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Batch-classify all settled signals that don't yet have a classification."""
    return await tmi.run_classification_pass()


@router.post("/signals/{analytics_id}/close")
@inject
async def record_position_close(
    analytics_id: int,
    body: dict = Body(...),
    current_user: CurrentUser = Depends(require_authenticated),
    tmi: TradeManagementService = Depends(
        Provide[ApplicationContainer.trade_management_service]
    ),
) -> dict[str, Any]:
    """Record the actual position exit price for a signal (trader-supplied)."""
    exit_price = body.get("exit_price")
    if exit_price is None:
        raise HTTPException(status_code=422, detail="exit_price is required")
    closed_at_raw = body.get("closed_at")
    closed_at = datetime.fromisoformat(closed_at_raw) if closed_at_raw else None

    result = await tmi.record_position_close(
        analytics_id=analytics_id,
        exit_price=float(exit_price),
        closed_at=closed_at,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
