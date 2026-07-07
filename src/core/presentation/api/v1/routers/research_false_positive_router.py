"""Research false positive analysis router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import FalsePositiveListResponse

router = APIRouter(prefix="/api/v1/research/false-positive", tags=["Research — False Positive Analysis"])


@router.get("", response_model=FalsePositiveListResponse, summary="Get false positive analysis")
@inject
async def get_analysis(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_false_positive_analyzer_service]),
) -> FalsePositiveListResponse:
    analysis = await svc.get_analysis()
    return FalsePositiveListResponse(analysis=analysis, total=len(analysis))


@router.post("/compute", summary="Recompute false positive analysis")
@inject
async def compute_analysis(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_false_positive_analyzer_service]),
) -> dict:
    await svc.compute_analysis(lookback_days=lookback_days)
    return {"status": "computed", "lookback_days": lookback_days}
