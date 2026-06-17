"""News & Sentiment Router.

GET  /api/v1/news                         — recent news events
GET  /api/v1/news/sentiment/market        — overall market sentiment
GET  /api/v1/news/sentiment/{symbol}      — per-symbol sentiment
POST /api/v1/news/refresh                 — trigger news aggregation
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.news_aggregation_service import NewsAggregationService
from core.application.services.sentiment_service import SentimentService

router = APIRouter(prefix="/news", tags=["news"])


@router.get("")
@inject
async def get_news(
    limit: int = Query(50, ge=1, le=200),
    symbol: str | None = Query(None),
    news_svc: NewsAggregationService = Depends(Provide[ApplicationContainer.news_aggregation_service]),
):
    from dataclasses import asdict
    events = await news_svc.get_recent(limit=limit, symbol=symbol)
    return {"events": [asdict(e) for e in events]}


@router.get("/sentiment/market")
@inject
async def get_market_sentiment(
    sentiment_svc: SentimentService = Depends(Provide[ApplicationContainer.sentiment_service]),
):
    return await sentiment_svc.get_market_sentiment()


@router.get("/sentiment/{symbol}")
@inject
async def get_symbol_sentiment(
    symbol: str,
    hours: int = Query(24, ge=1, le=168),
    sentiment_svc: SentimentService = Depends(Provide[ApplicationContainer.sentiment_service]),
):
    return await sentiment_svc.get_symbol_sentiment(symbol.upper(), hours=hours)


@router.post("/refresh")
@inject
async def refresh_news(
    news_svc: NewsAggregationService = Depends(Provide[ApplicationContainer.news_aggregation_service]),
):
    count = await news_svc.fetch_all()
    return {"fetched": count}
