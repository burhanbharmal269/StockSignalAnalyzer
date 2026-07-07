"""Research feature importance router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import FeatureImportanceListResponse

router = APIRouter(prefix="/api/v1/research/feature-importance", tags=["Research — Feature Importance"])


@router.get("", response_model=FeatureImportanceListResponse, summary="Get feature importance")
@inject
async def get_importance(
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_feature_importance_service]),
) -> FeatureImportanceListResponse:
    importance = await svc.get_importance()
    return FeatureImportanceListResponse(importance=importance)


@router.post("/compute", summary="Recompute feature importance")
@inject
async def compute_importance(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_feature_importance_service]),
) -> dict:
    result = await svc.compute_importance(lookback_days=lookback_days)
    return {"computed": len(result), "importance": result}
