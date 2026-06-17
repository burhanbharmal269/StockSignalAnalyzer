"""Paper Trading Daemon Router.

GET  /api/v1/paper/status                 — daemon status, open positions
POST /api/v1/paper/start                  — start the daemon
POST /api/v1/paper/stop                   — stop the daemon
GET  /api/v1/paper/journal                — trade journal
GET  /api/v1/paper/performance            — P&L summary
"""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.paper_trading_daemon import PaperTradingDaemon

router = APIRouter(prefix="/paper", tags=["paper-trading"])


@router.get("/status")
@inject
async def get_status(
    daemon: PaperTradingDaemon = Depends(Provide[ApplicationContainer.paper_trading_daemon]),
):
    return daemon.status()


@router.post("/start")
@inject
async def start_daemon(
    daemon: PaperTradingDaemon = Depends(Provide[ApplicationContainer.paper_trading_daemon]),
):
    await daemon.start()
    return {"started": True, "status": daemon.status()}


@router.post("/stop")
@inject
async def stop_daemon(
    daemon: PaperTradingDaemon = Depends(Provide[ApplicationContainer.paper_trading_daemon]),
):
    await daemon.stop()
    return {"stopped": True}


@router.get("/journal")
@inject
async def get_journal(
    limit: int = Query(50, ge=1, le=500),
    daemon: PaperTradingDaemon = Depends(Provide[ApplicationContainer.paper_trading_daemon]),
):
    return {"journal": await daemon.get_journal(limit=limit)}


@router.get("/performance")
@inject
async def get_performance(
    daemon: PaperTradingDaemon = Depends(Provide[ApplicationContainer.paper_trading_daemon]),
):
    return await daemon.get_performance()
