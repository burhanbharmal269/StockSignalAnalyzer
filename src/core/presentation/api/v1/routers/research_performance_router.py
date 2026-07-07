"""Research performance metrics router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    CompareVersionsRequest,
    CompareVersionsResponse,
    PerformanceResponse,
)

router = APIRouter(prefix="/api/v1/research/performance", tags=["Research — Performance"])


@router.get("/{version_id}", response_model=PerformanceResponse,
            summary="Compute performance metrics for a version")
@inject
async def get_performance(
    version_id: str,
    lookback_days: int = Query(default=252),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_performance_metrics_service]),
) -> PerformanceResponse:
    latest = await svc.get_latest(version_id)
    if latest:
        return PerformanceResponse(version_id=version_id, **{
            k: v for k, v in latest.items()
            if k in PerformanceResponse.model_fields
        })
    metrics = await svc.compute_for_version(version_id, lookback_days=lookback_days)
    return PerformanceResponse(version_id=version_id, lookback_days=lookback_days, **metrics)


@router.post("/compare", response_model=CompareVersionsResponse, summary="Compare multiple versions")
@inject
async def compare_versions(
    body: CompareVersionsRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_performance_metrics_service]),
) -> CompareVersionsResponse:
    results = await svc.compare_versions(body.version_ids, lookback_days=body.lookback_days)
    return CompareVersionsResponse(
        comparisons=[
            PerformanceResponse(**{k: v for k, v in r.items() if k in PerformanceResponse.model_fields})
            for r in results
        ]
    )
