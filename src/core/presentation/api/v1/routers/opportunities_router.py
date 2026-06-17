"""Opportunities Router.

GET  /api/v1/opportunities                — current ranked opportunities
POST /api/v1/opportunities/scan           — trigger full scanner run
GET  /api/v1/opportunities/{id}           — single opportunity detail
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.opportunity_ranking_service import OpportunityRankingService

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("")
@inject
async def get_opportunities(
    limit: int = Query(20, ge=1, le=100),
    direction: str | None = Query(None, description="LONG | SHORT"),
    type: str | None = Query(None, description="BREAKOUT | BREAKDOWN | MOMENTUM | ..."),
    ranking_svc: OpportunityRankingService = Depends(Provide[ApplicationContainer.opportunity_ranking_service]),
):
    ops = await ranking_svc.get_top(limit=limit)
    if direction:
        ops = [o for o in ops if o.get("direction") == direction.upper()]
    if type:
        ops = [o for o in ops if o.get("type") == type.upper()]
    return {"opportunities": ops, "count": len(ops)}


@router.post("/scan")
@inject
async def run_scan(
    timeframe: str = Query("15m"),
    ranking_svc: OpportunityRankingService = Depends(Provide[ApplicationContainer.opportunity_ranking_service]),
):
    """Trigger a fresh scan of the full universe. May take 30-120s."""
    results = await ranking_svc.run_full_scan(timeframe=timeframe)
    return {"scanned": len(results), "top_opportunities": results[:10]}
