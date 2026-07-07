"""Research component correlations router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import CorrelationListResponse

router = APIRouter(prefix="/api/v1/research/correlations", tags=["Research — Correlations"])


@router.get("", response_model=CorrelationListResponse, summary="Get component correlations")
@inject
async def get_correlations(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_component_correlation_service]),
) -> CorrelationListResponse:
    corrs = await svc.get_correlations(lookback_days=lookback_days)
    return CorrelationListResponse(correlations=corrs, total=len(corrs))


@router.post("/compute", summary="Recompute correlations")
@inject
async def compute_correlations(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_component_correlation_service]),
) -> dict:
    result = await svc.compute_correlations(lookback_days=lookback_days)
    return result
