"""Research optimization router — grid search endpoints."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    OptimizationResultsResponse,
    RunStatusResponse,
    StartGridSearchRequest,
)

router = APIRouter(prefix="/api/v1/research/optimization", tags=["Research — Optimization"])


@router.post("/start", summary="Start a grid search run")
@inject
async def start_grid_search(
    body: StartGridSearchRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_parameter_optimization_service]),
) -> dict:
    run_id = await svc.start_grid_search(
        version_id=body.version_id,
        param_grid=body.param_grid,
        metric=body.metric,
        lookback_days=body.lookback_days,
    )
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/{run_id}/status", response_model=RunStatusResponse, summary="Get run status")
@inject
async def get_run_status(
    run_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_parameter_optimization_service]),
) -> RunStatusResponse:
    status_data = await svc.get_run_status(run_id)
    return RunStatusResponse(**status_data) if status_data else RunStatusResponse()


@router.get("/{run_id}/results", response_model=OptimizationResultsResponse,
            summary="Get optimization results")
@inject
async def get_results(
    run_id: str,
    limit: int = Query(default=100, le=500),
    sort_by: str = Query(default="sharpe"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_parameter_optimization_service]),
) -> OptimizationResultsResponse:
    results = await svc.get_results(run_id, limit=limit, sort_by=sort_by)
    return OptimizationResultsResponse(run_id=run_id, results=results, total=len(results))


@router.get("/{run_id}/best", summary="Get best parameter combination")
@inject
async def get_best_params(
    run_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_parameter_optimization_service]),
) -> dict:
    return await svc.get_best_params(run_id)
