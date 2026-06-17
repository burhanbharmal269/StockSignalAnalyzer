"""AI Insights Router.

GET  /api/v1/ai/market                    — latest market insight
GET  /api/v1/ai/market/history            — insight history
POST /api/v1/ai/market/generate           — trigger fresh insight generation
GET  /api/v1/ai/strategy/{symbol}         — strategy recommendation for symbol
POST /api/v1/ai/news/analyze              — analyze specific news event
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.ai.market_analyst_service import MarketAnalystService
from core.application.services.ai.news_analyst_service import NewsAnalystService
from core.application.services.ai.strategy_selector_service import StrategySelectorService

router = APIRouter(prefix="/ai", tags=["ai-insights"])


@router.get("/market")
@inject
async def get_market_insight(
    analyst: MarketAnalystService = Depends(Provide[ApplicationContainer.market_analyst_service]),
):
    insight = await analyst.get_latest()
    return insight or {"message": "no_insight_yet"}


@router.get("/market/history")
@inject
async def get_insight_history(
    limit: int = Query(7, ge=1, le=30),
    analyst: MarketAnalystService = Depends(Provide[ApplicationContainer.market_analyst_service]),
):
    return {"history": await analyst.get_history(limit=limit)}


@router.post("/market/generate")
@inject
async def generate_market_insight(
    analyst: MarketAnalystService = Depends(Provide[ApplicationContainer.market_analyst_service]),
):
    return await analyst.generate_daily_insight()


@router.get("/strategy/{symbol}")
@inject
async def get_strategy_recommendation(
    symbol: str,
    regime: str = Query("UNKNOWN"),
    timeframe: str = Query("15m"),
    is_index: bool = Query(False),
    selector: StrategySelectorService = Depends(Provide[ApplicationContainer.strategy_selector_service]),
):
    return await selector.recommend_for_symbol(
        symbol=symbol.upper(),
        regime=regime.upper(),
        timeframe=timeframe,
        is_index=is_index,
    )
