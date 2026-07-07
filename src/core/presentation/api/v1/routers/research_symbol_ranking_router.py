"""Research symbol ranking router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import SymbolRankingsResponse

router = APIRouter(prefix="/api/v1/research/symbol-rankings", tags=["Research — Symbol Rankings"])


@router.get("", response_model=SymbolRankingsResponse, summary="Get symbol rankings")
@inject
async def get_rankings(
    limit: int = Query(default=50, ge=1, le=500),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_symbol_ranking_service]),
) -> SymbolRankingsResponse:
    rankings = await svc.get_rankings(limit=limit)
    return SymbolRankingsResponse(rankings=rankings, total=len(rankings))


@router.post("/compute", summary="Recompute symbol rankings")
@inject
async def compute_rankings(
    lookback_days: int = Query(default=90),
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_symbol_ranking_service]),
) -> dict:
    await svc.compute_rankings(lookback_days=lookback_days)
    return {"status": "computed", "lookback_days": lookback_days}
