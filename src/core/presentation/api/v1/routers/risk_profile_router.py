"""Risk Profile API router.

Endpoints:
  GET    /api/v1/risk-profiles           — list all
  POST   /api/v1/risk-profiles           — create
  GET    /api/v1/risk-profiles/active    — get active profile
  GET    /api/v1/risk-profiles/{id}      — get by id
  PATCH  /api/v1/risk-profiles/{id}      — update fields
  POST   /api/v1/risk-profiles/{id}/activate   — activate
  POST   /api/v1/risk-profiles/{id}/deactivate — deactivate
"""

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status

from container import ApplicationContainer
from core.application.services.risk_profile_service import RiskProfileService
from core.presentation.api.v1.schemas.capital_framework import (
    CreateRiskProfileRequest,
    RiskProfileListResponse,
    RiskProfileResponse,
    UpdateRiskProfileRequest,
)

router = APIRouter(prefix="/api/v1/risk-profiles", tags=["Risk Profiles"])


def _to_response(profile: object) -> RiskProfileResponse:
    return RiskProfileResponse.model_validate(profile)


@router.get("", response_model=RiskProfileListResponse)
@inject
async def list_risk_profiles(
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileListResponse:
    profiles = await service.list_all()
    return RiskProfileListResponse(
        profiles=[_to_response(p) for p in profiles],
        total=len(profiles),
    )


@router.get("/active", response_model=RiskProfileResponse)
@inject
async def get_active_risk_profile(
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    profile = await service.get_active()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active risk profile")
    return _to_response(profile)


@router.get("/{profile_id}", response_model=RiskProfileResponse)
@inject
async def get_risk_profile(
    profile_id: uuid.UUID,
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    profile = await service.get_by_id(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk profile not found")
    return _to_response(profile)


@router.post("", response_model=RiskProfileResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_risk_profile(
    request: Request,
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    body = CreateRiskProfileRequest(**(await request.json()))
    try:
        profile = await service.create(
            name=body.name,
            profile_type=body.profile_type,
            universe_scope=body.universe_scope,
            risk_per_trade_pct=body.risk_per_trade_pct,
            max_open_positions=body.max_open_positions,
            daily_loss_pct=body.daily_loss_pct,
            weekly_loss_pct=body.weekly_loss_pct,
            drawdown_pct=body.drawdown_pct,
            max_position_size_pct=body.max_position_size_pct,
            min_position_size_lots=body.min_position_size_lots,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(profile)


@router.patch("/{profile_id}", response_model=RiskProfileResponse)
@inject
async def update_risk_profile(
    request: Request,
    profile_id: uuid.UUID,
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    body = UpdateRiskProfileRequest(**(await request.json()))
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update")
    try:
        profile = await service.update(profile_id, **updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(profile)


@router.post("/{profile_id}/activate", response_model=RiskProfileResponse)
@inject
async def activate_risk_profile(
    profile_id: uuid.UUID,
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    try:
        profile = await service.activate(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(profile)


@router.post("/{profile_id}/deactivate", response_model=RiskProfileResponse)
@inject
async def deactivate_risk_profile(
    profile_id: uuid.UUID,
    service: RiskProfileService = Depends(Provide[ApplicationContainer.risk_profile_service]),  # noqa: B008
) -> RiskProfileResponse:
    try:
        profile = await service.deactivate(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(profile)
