"""Portfolio API router.

Endpoints:
  GET    /api/v1/portfolios           — list all
  POST   /api/v1/portfolios           — create
  GET    /api/v1/portfolios/active    — get active portfolio
  GET    /api/v1/portfolios/{id}      — get by id
  POST   /api/v1/portfolios/{id}/activate   — activate
  POST   /api/v1/portfolios/{id}/deactivate — deactivate
"""

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status

from container import ApplicationContainer
from core.application.services.portfolio_service import PortfolioService
from core.presentation.api.v1.schemas.capital_framework import (
    CreatePortfolioRequest,
    PortfolioListResponse,
    PortfolioResponse,
)

router = APIRouter(prefix="/api/v1/portfolios", tags=["Portfolios"])


def _to_response(portfolio: object) -> PortfolioResponse:
    return PortfolioResponse.model_validate(portfolio)


@router.get("", response_model=PortfolioListResponse)
@inject
async def list_portfolios(
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioListResponse:
    portfolios = await service.list_all()
    return PortfolioListResponse(
        portfolios=[_to_response(p) for p in portfolios],
        total=len(portfolios),
    )


@router.get("/active", response_model=PortfolioResponse)
@inject
async def get_active_portfolio(
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioResponse:
    portfolio = await service.get_active()
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio")
    return _to_response(portfolio)


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
@inject
async def get_portfolio(
    portfolio_id: uuid.UUID,
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioResponse:
    portfolio = await service.get_by_id(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    return _to_response(portfolio)


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_portfolio(
    request: Request,
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioResponse:
    body = CreatePortfolioRequest(**(await request.json()))
    try:
        portfolio = await service.create(
            name=body.name,
            portfolio_type=body.portfolio_type,
            risk_profile_id=body.risk_profile_id,
            allocation_id=body.allocation_id,
            owner_user_id=body.owner_user_id,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_response(portfolio)


@router.post("/{portfolio_id}/activate", response_model=PortfolioResponse)
@inject
async def activate_portfolio(
    portfolio_id: uuid.UUID,
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioResponse:
    try:
        portfolio = await service.activate(portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(portfolio)


@router.post("/{portfolio_id}/deactivate", response_model=PortfolioResponse)
@inject
async def deactivate_portfolio(
    portfolio_id: uuid.UUID,
    service: PortfolioService = Depends(Provide[ApplicationContainer.portfolio_service]),  # noqa: B008
) -> PortfolioResponse:
    try:
        portfolio = await service.deactivate(portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(portfolio)
