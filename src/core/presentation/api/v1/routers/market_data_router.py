"""Market Data Router.

GET  /api/v1/market/universe              — full symbol list
GET  /api/v1/market/candles/{symbol}      — historical candles
GET  /api/v1/market/ltp                   — live last-traded prices
GET  /api/v1/market/breadth               — current market breadth
GET  /api/v1/market/breadth/history       — breadth history
POST /api/v1/market/fetch                 — trigger historical data fetch
"""


from datetime import datetime
from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.daily_universe_builder_service import DailyUniverseBuilderService
from core.application.services.market_breadth_service import MarketBreadthService
from core.application.services.market_data.historical_data_service import HistoricalDataService
from core.application.services.market_data.live_feed_service import LiveMarketFeedService
from core.application.services.market_universe_service import MarketUniverseService
from core.presentation.api.v1.dependencies.auth import require_no_force_change

router = APIRouter(prefix="/market", tags=["market-data"])


@router.get("/universe")
@inject
async def get_universe(
    segment: str | None = Query(None),
    fo_only: bool = Query(False),
    universe_svc: MarketUniverseService = Depends(Provide[ApplicationContainer.market_universe_service]),
):
    symbols = await universe_svc.get_active_symbols(segment=segment, fo_only=fo_only)
    return {"symbols": [{"symbol": s.symbol, "name": s.name, "sector": s.sector,
                          "is_fo": s.is_fo, "is_index": s.is_index} for s in symbols]}


@router.get("/candles/{symbol}")
@inject
async def get_candles(
    symbol: str,
    timeframe: str = Query("15m"),
    limit: int = Query(100, ge=1, le=1000),
    historical_svc: HistoricalDataService = Depends(Provide[ApplicationContainer.historical_data_service]),
):
    candles = await historical_svc.get_latest(symbol, timeframe, limit)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [
            {"ts": c.ts.isoformat(), "open": float(c.open), "high": float(c.high),
             "low": float(c.low), "close": float(c.close), "volume": float(c.volume)}
            for c in candles
        ],
    }


@router.get("/ltp")
@inject
async def get_ltp(
    symbols: str = Query(..., description="Comma-separated symbol list"),
    live_feed: LiveMarketFeedService = Depends(Provide[ApplicationContainer.live_feed_service]),
):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    prices = {}
    for sym in sym_list:
        price = await live_feed.get_ltp(sym)
        if price is not None:
            prices[sym] = float(price)
    return {"prices": prices}


@router.get("/breadth")
@inject
async def get_breadth(
    breadth_svc: MarketBreadthService = Depends(Provide[ApplicationContainer.market_breadth_service]),
):
    return await breadth_svc.get_latest() or {"message": "no_data"}


@router.post("/universe/seed")
@inject
async def seed_universe(
    universe_svc: MarketUniverseService = Depends(Provide[ApplicationContainer.market_universe_service]),
):
    """Seed the universe with default NSE/F&O symbols. Idempotent."""
    count = await universe_svc.seed_default_universe()
    return {"seeded": count, "message": f"{count} symbols in universe"}


@router.post("/universe/sync-kite")
@inject
async def sync_universe_from_kite(
    universe_svc: MarketUniverseService = Depends(Provide[ApplicationContainer.market_universe_service]),
    broker_config=Depends(Provide[ApplicationContainer.broker_config]),
    session_repo=Depends(Provide[ApplicationContainer.broker_session_repository]),
    token_encryptor=Depends(Provide[ApplicationContainer.token_encryptor]),
):
    """Sync instrument metadata (sector, token, lot_size) from Kite instruments API."""
    session = await session_repo.get_active("kite")
    if not session:
        return {"error": "No active Kite session. Connect to Kite first."}
    access_token = await token_encryptor.decrypt(session.encrypted_access_token)
    updated = await universe_svc.sync_from_kite(
        api_key=broker_config.kite_api_key,
        access_token=access_token,
    )
    return {"updated": updated, "message": f"Synced metadata for {updated} symbols from Kite"}


@router.get("/breadth/history")
@inject
async def get_breadth_history(
    limit: int = Query(30, ge=1, le=200),
    breadth_svc: MarketBreadthService = Depends(Provide[ApplicationContainer.market_breadth_service]),
):
    return {"history": await breadth_svc.get_history(limit)}


@router.post("/fetch")
@inject
async def trigger_fetch(
    symbol: str = Query(...),
    timeframe: str = Query("D"),
    days: int = Query(365, ge=1, le=3650),
    historical_svc: HistoricalDataService = Depends(Provide[ApplicationContainer.historical_data_service]),
):
    """Trigger a gap-fill historical data fetch for a symbol."""
    from datetime import datetime, timedelta, UTC
    to_dt = datetime.now(UTC)
    from_dt = to_dt - timedelta(days=days)
    count = await historical_svc.fetch_and_store(symbol, timeframe, from_dt=from_dt, to_dt=to_dt)
    return {"symbol": symbol, "timeframe": timeframe, "candles_stored": count}


@router.post("/fetch/bulk")
@inject
async def trigger_bulk_fetch(
    timeframe: str = Query("15m"),
    days: int = Query(60, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    include_indices: bool = Query(True, description="Also fetch index futures (NIFTY, BANKNIFTY, etc.)"),
    universe_svc: MarketUniverseService = Depends(Provide[ApplicationContainer.market_universe_service]),
    historical_svc: HistoricalDataService = Depends(Provide[ApplicationContainer.historical_data_service]),
):
    """Fetch historical candles for the full F&O universe (stocks + index futures) from Kite."""
    from datetime import datetime, timedelta, UTC
    to_dt   = datetime.now(UTC)
    from_dt = to_dt - timedelta(days=days)

    all_symbols = await universe_svc.get_active_symbols(fo_only=True)
    indices    = [s.symbol for s in all_symbols if s.is_index] if include_indices else []
    fo_stocks  = [s.symbol for s in all_symbols if not s.is_index][:max(limit - len(indices), 0)]
    fetch_list = indices + fo_stocks

    results: dict[str, int] = {}
    for sym in fetch_list:
        try:
            count = await historical_svc.fetch_and_store(sym, timeframe, from_dt=from_dt, to_dt=to_dt)
            results[sym] = count
        except Exception:
            results[sym] = -1

    total = sum(v for v in results.values() if v > 0)
    return {
        "symbols_fetched": len(fetch_list),
        "indices_included": len(indices),
        "fo_stocks_included": len(fo_stocks),
        "total_candles": total,
        "detail": results,
    }


@router.post("/universe/reseed")
@inject
async def reseed_universe(
    _user=Depends(require_no_force_change),
    universe_svc: MarketUniverseService = Depends(Provide[ApplicationContainer.market_universe_service]),
):
    """Force-upsert all universe symbols (picks up newly added stocks/indices)."""
    total = await universe_svc.seed_default_universe(force=True)
    return {"seeded": total, "message": f"Upserted {total} symbols into market_universe"}


@router.post("/universe/build")
@inject
async def build_daily_universe(
    _user=Depends(require_no_force_change),
    builder: DailyUniverseBuilderService = Depends(Provide[ApplicationContainer.daily_universe_builder_service]),
):
    """Build today's prioritised trading universe (index futures + ranked F&O stocks)."""
    universe = await builder.build()
    return {
        "built_at": universe.built_at.isoformat(),
        "total_candidates": universe.total_candidates,
        "index_futures": [
            {"symbol": c.symbol, "priority_score": c.priority_score, "reason": c.reason}
            for c in universe.index_futures
        ],
        "top_50_stocks": [
            {
                "symbol":         c.symbol,
                "sector":         c.sector,
                "priority_score": round(c.priority_score, 1),
                "volume_score":   round(c.volume_score, 2),
                "momentum_score": round(c.momentum_score, 2),
                "reason":         c.reason,
            }
            for c in sorted(universe.fo_stocks, key=lambda x: x.priority_score, reverse=True)[:50]
        ],
        "sector_breakdown": universe.sector_breakdown,
        "all_symbols_count": len(universe.all_candidates),
    }
