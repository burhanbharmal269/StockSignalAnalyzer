"""Backtest Router.

POST /api/v1/backtest/run                 — run a backtest
GET  /api/v1/backtest/runs                — list past runs
GET  /api/v1/backtest/runs/{run_id}       — run details + metrics
GET  /api/v1/backtest/runs/{run_id}/trades — trade list for a run
"""

from __future__ import annotations

from datetime import datetime

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from container import ApplicationContainer
from core.application.services.backtest_service import BacktestService

router = APIRouter(prefix="/backtest", tags=["backtest"])

_STRATEGY_MAP = {
    "EMA_TREND": "core.domain.strategies.ema_trend_strategy.EMATrendStrategy",
    "VWAP_PULLBACK": "core.domain.strategies.vwap_pullback_strategy.VWAPPullbackStrategy",
    "ORB": "core.domain.strategies.orb_strategy.ORBStrategy",
    "MOMENTUM": "core.domain.strategies.momentum_strategy.MomentumStrategy",
    "OI_STRATEGY": "core.domain.strategies.oi_strategy.OIStrategy",
    "REGIME_ADAPTIVE": "core.domain.strategies.regime_adaptive_strategy.RegimeAdaptiveStrategy",
}


def _load_strategy(name: str):
    import importlib
    path = _STRATEGY_MAP.get(name.upper())
    if not path:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {name}")
    module_path, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    timeframe: str = "15m"
    from_dt: datetime
    to_dt: datetime
    initial_capital: float = 100000.0
    risk_per_trade_pct: float = 1.0
    params: dict = {}


@router.post("/run")
@inject
async def run_backtest(
    request: BacktestRequest,
    backtest_svc: BacktestService = Depends(Provide[ApplicationContainer.backtest_service]),
):
    from decimal import Decimal
    strategy = _load_strategy(request.strategy)
    result = await backtest_svc.run(
        strategy=strategy,
        symbol=request.symbol.upper(),
        timeframe=request.timeframe,
        from_dt=request.from_dt,
        to_dt=request.to_dt,
        initial_capital=Decimal(str(request.initial_capital)),
        risk_per_trade_pct=Decimal(str(request.risk_per_trade_pct)),
        params=request.params or None,
    )
    return result


@router.get("/runs")
@inject
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    backtest_svc: BacktestService = Depends(Provide[ApplicationContainer.backtest_service]),
):
    return {"runs": await backtest_svc.list_runs(limit=limit)}


@router.get("/runs/{run_id}/trades")
@inject
async def get_trades(
    run_id: str,
    backtest_svc: BacktestService = Depends(Provide[ApplicationContainer.backtest_service]),
):
    trades = await backtest_svc.get_trades(run_id)
    return {"run_id": run_id, "trades": trades}
