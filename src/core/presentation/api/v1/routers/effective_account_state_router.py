"""Effective Account State API router.

Endpoints:
  GET /api/v1/effective-account-state — resolve and return current effective state
"""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from container import ApplicationContainer
from core.application.services.effective_account_state_service import EffectiveAccountStateService
from core.domain.exceptions.risk import RiskInvariantError
from core.presentation.api.v1.schemas.capital_framework import EffectiveAccountStateResponse

router = APIRouter(prefix="/api/v1/effective-account-state", tags=["Effective Account State"])


@router.get("", response_model=EffectiveAccountStateResponse)
@inject
async def get_effective_account_state(
    service: EffectiveAccountStateService = Depends(  # noqa: B008
        Provide[ApplicationContainer.effective_account_state_service]
    ),
) -> EffectiveAccountStateResponse:
    try:
        eas = await service.resolve()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not resolve effective account state: {exc}",
        ) from exc
    return EffectiveAccountStateResponse(
        capital_source_mode=eas.capital_source_mode,
        broker_capital=eas.broker_capital,
        broker_margin=eas.broker_margin,
        configured_capital=eas.configured_capital,
        configured_margin=eas.configured_margin,
        effective_capital=eas.effective_capital,
        effective_margin=eas.effective_margin,
        effective_daily_loss_limit=eas.effective_daily_loss_limit,
        effective_weekly_loss_limit=eas.effective_weekly_loss_limit,
        effective_drawdown_limit=eas.effective_drawdown_limit,
        effective_risk_per_trade=eas.effective_risk_per_trade,
        effective_max_open_positions=eas.effective_max_open_positions,
        risk_profile_id=eas.risk_profile_id,
        allocation_id=eas.allocation_id,
        portfolio_id=eas.portfolio_id,
        captured_at=eas.captured_at,
    )
