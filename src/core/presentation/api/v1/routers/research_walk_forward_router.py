"""Research walk-forward router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    StartWalkForwardRequest,
    WalkForwardWindowsResponse,
)

router = APIRouter(prefix="/api/v1/research/walk-forward", tags=["Research — Walk-Forward"])


@router.post("/start", summary="Start a walk-forward analysis run")
@inject
async def start_run(
    body: StartWalkForwardRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_walk_forward_analyzer_service]),
) -> dict:
    run_id = await svc.start_run(
        version_id=body.version_id,
        from_dt=body.from_dt,
        to_dt=body.to_dt,
        n_windows=body.n_windows,
    )
    return {"run_id": run_id, "status": "RUNNING"}


@router.get("/{run_id}/windows", response_model=WalkForwardWindowsResponse,
            summary="Get walk-forward windows")
@inject
async def get_windows(
    run_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_walk_forward_analyzer_service]),
) -> WalkForwardWindowsResponse:
    windows = await svc.get_windows(run_id)
    aggregate = await svc.get_aggregate_oos_stats(run_id)
    return WalkForwardWindowsResponse(run_id=run_id, windows=windows, aggregate=aggregate)


@router.get("/{run_id}/aggregate", summary="Get aggregate OOS statistics")
@inject
async def get_aggregate(
    run_id: str,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_walk_forward_analyzer_service]),
) -> dict:
    return await svc.get_aggregate_oos_stats(run_id)
