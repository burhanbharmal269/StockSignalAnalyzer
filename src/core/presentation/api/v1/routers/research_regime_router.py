"""Research regime performance router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import RegimePerformanceListResponse

router = APIRouter(prefix="/api/v1/research/regime-performance", tags=["Research — Regime Performance"])


@router.get("", response_model=RegimePerformanceListResponse, summary="Get regime performance")
@inject
async def get_regime_breakdown(
    lookback_days: int = Query(default=90),
    version_id: str | None = Query(default=None),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_regime_performance_service]),
) -> RegimePerformanceListResponse:
    breakdown = await svc.get_regime_breakdown(version_id=version_id, lookback_days=lookback_days)
    return RegimePerformanceListResponse(breakdown=breakdown, total=len(breakdown))


@router.post("/compute", summary="Recompute regime performance")
@inject
async def compute_regime_performance(
    lookback_days: int = Query(default=90),
    version_id: str | None = Query(default=None),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_regime_performance_service]),
) -> dict:
    await svc.compute(lookback_days=lookback_days, version_id=version_id)
    return {"status": "computed", "lookback_days": lookback_days}
