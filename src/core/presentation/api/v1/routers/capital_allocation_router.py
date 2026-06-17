"""Capital Allocation API router.

Endpoints:
  GET    /api/v1/capital-allocations           — list all
  POST   /api/v1/capital-allocations           — create
  GET    /api/v1/capital-allocations/active    — get active allocation
  GET    /api/v1/capital-allocations/{id}      — get by id
  PATCH  /api/v1/capital-allocations/{id}/capital — update capital amounts
  PATCH  /api/v1/capital-allocations/{id}/mode   — update source mode
  POST   /api/v1/capital-allocations/{id}/activate   — activate
  POST   /api/v1/capital-allocations/{id}/deactivate — deactivate
"""

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status

from container import ApplicationContainer
from core.application.services.capital_allocation_service import CapitalAllocationService
from core.presentation.api.v1.schemas.capital_framework import (
    CapitalAllocationListResponse,
    CapitalAllocationResponse,
    CreateCapitalAllocationRequest,
    UpdateCapitalRequest,
    UpdateModeRequest,
)

router = APIRouter(prefix="/api/v1/capital-allocations", tags=["Capital Allocations"])


def _to_response(allocation: object) -> CapitalAllocationResponse:
    return CapitalAllocationResponse.model_validate(allocation)


@router.get("", response_model=CapitalAllocationListResponse)
@inject
async def list_capital_allocations(
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationListResponse:
    allocations = await service.list_all()
    return CapitalAllocationListResponse(
        allocations=[_to_response(a) for a in allocations],
        total=len(allocations),
    )


@router.get("/active", response_model=CapitalAllocationResponse)
@inject
async def get_active_allocation(
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    allocation = await service.get_active()
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active capital allocation")
    return _to_response(allocation)


@router.get("/{allocation_id}", response_model=CapitalAllocationResponse)
@inject
async def get_capital_allocation(
    allocation_id: uuid.UUID,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    allocation = await service.get_by_id(allocation_id)
    if allocation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capital allocation not found")
    return _to_response(allocation)


@router.post("", response_model=CapitalAllocationResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_capital_allocation(
    request: Request,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    body = CreateCapitalAllocationRequest(**(await request.json()))
    try:
        allocation = await service.create(
            name=body.name,
            allocation_type=body.allocation_type,
            universe_scope=body.universe_scope,
            allocated_capital=body.allocated_capital,
            capital_source_mode=body.capital_source_mode,
            allocated_margin=body.allocated_margin,
            strategy_type=body.strategy_type,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(allocation)


@router.patch("/{allocation_id}/capital", response_model=CapitalAllocationResponse)
@inject
async def update_capital(
    request: Request,
    allocation_id: uuid.UUID,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    body = UpdateCapitalRequest(**(await request.json()))
    try:
        allocation = await service.update_capital(
            allocation_id=allocation_id,
            new_capital=body.new_capital,
            new_margin=body.new_margin,
            changed_by=body.changed_by,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(allocation)


@router.patch("/{allocation_id}/mode", response_model=CapitalAllocationResponse)
@inject
async def update_mode(
    request: Request,
    allocation_id: uuid.UUID,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    body = UpdateModeRequest(**(await request.json()))
    try:
        allocation = await service.update_mode(
            allocation_id=allocation_id,
            mode=body.capital_source_mode,
            changed_by=body.changed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(allocation)


@router.post("/{allocation_id}/activate", response_model=CapitalAllocationResponse)
@inject
async def activate_allocation(
    allocation_id: uuid.UUID,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    try:
        allocation = await service.activate(allocation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(allocation)


@router.post("/{allocation_id}/deactivate", response_model=CapitalAllocationResponse)
@inject
async def deactivate_allocation(
    allocation_id: uuid.UUID,
    service: CapitalAllocationService = Depends(Provide[ApplicationContainer.capital_allocation_service]),  # noqa: B008
) -> CapitalAllocationResponse:
    try:
        allocation = await service.deactivate(allocation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(allocation)
