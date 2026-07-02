"""Phase 23 — Execution Intelligence REST API.

All endpoints are read-only analytics. No trading side effects.

Prefix: /api/v1/execution
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Execution Intelligence"])


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/execution/timeline/{signal_id}")
@inject
async def get_timeline(
    signal_id: str,
    timeline_svc=Depends(Provide[ApplicationContainer.execution_timeline_service]),
) -> dict[str, Any]:
    """Full execution timeline for a single signal."""
    result = await timeline_svc.get_timeline(signal_id)
    return result or {"detail": "not_found"}


@router.get("/execution/timeline")
@inject
async def get_recent_timeline(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    timeline_svc=Depends(Provide[ApplicationContainer.execution_timeline_service]),
) -> list[dict[str, Any]]:
    """Recent execution timelines."""
    return await timeline_svc.get_recent(limit=limit)


@router.get("/execution/timeline/slowest")
@inject
async def get_slowest_executions(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    timeline_svc=Depends(Provide[ApplicationContainer.execution_timeline_service]),
) -> list[dict[str, Any]]:
    """Slowest executions by total_execution_ms."""
    return await timeline_svc.get_slowest(limit=limit)


# ── Latency ───────────────────────────────────────────────────────────────────

@router.get("/execution/latency/stats")
@inject
async def get_latency_stats(
    stage: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    latency_svc=Depends(Provide[ApplicationContainer.execution_latency_service]),
) -> dict[str, Any]:
    """Latency statistics (avg/p50/p95/p99/max) filtered by stage/broker/symbol."""
    return await latency_svc.get_stats(stage=stage, broker=broker, symbol=symbol, hours=hours)


@router.get("/execution/latency/windows")
@inject
async def get_latency_windows(
    stage: str = "total_execution",
    latency_svc=Depends(Provide[ApplicationContainer.execution_latency_service]),
) -> dict[str, Any]:
    """Rolling latency averages: 1D/7D/30D/90D/Lifetime."""
    return await latency_svc.get_rolling_windows(stage=stage)


@router.get("/execution/latency/by-broker")
@inject
async def get_latency_by_broker(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    latency_svc=Depends(Provide[ApplicationContainer.execution_latency_service]),
) -> dict[str, Any]:
    """Total execution latency comparison across brokers."""
    return await latency_svc.get_by_broker(hours=hours)


# ── Slippage ──────────────────────────────────────────────────────────────────

@router.get("/execution/slippage/stats")
@inject
async def get_slippage_stats(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    broker: str | None = None,
    slippage_svc=Depends(Provide[ApplicationContainer.execution_slippage_service]),
) -> dict[str, Any]:
    """Slippage statistics over recent window."""
    return await slippage_svc.get_slippage_stats(hours=hours, broker=broker)


@router.get("/execution/fill-quality/stats")
@inject
async def get_fill_quality_stats(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    slippage_svc=Depends(Provide[ApplicationContainer.execution_slippage_service]),
) -> dict[str, Any]:
    """Fill quality score statistics."""
    return await slippage_svc.get_fill_quality_stats(hours=hours)


# ── Rejections ────────────────────────────────────────────────────────────────

@router.get("/execution/rejections/stats")
@inject
async def get_rejection_stats(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    rejection_svc=Depends(Provide[ApplicationContainer.execution_rejection_service]),
) -> dict[str, Any]:
    """Rejection breakdown by category."""
    return await rejection_svc.get_stats(hours=hours)


@router.get("/execution/rejections/recent")
@inject
async def get_recent_rejections(
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    rejection_svc=Depends(Provide[ApplicationContainer.execution_rejection_service]),
) -> list[dict[str, Any]]:
    """Most recent rejections with category + raw reason."""
    return await rejection_svc.get_recent(limit=limit)


# ── Retries ───────────────────────────────────────────────────────────────────

@router.get("/execution/retries/stats")
@inject
async def get_retry_stats(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    retry_svc=Depends(Provide[ApplicationContainer.execution_retry_service]),
) -> dict[str, Any]:
    """Retry statistics: total, success rate, top reasons."""
    return await retry_svc.get_stats(hours=hours)


# ── Broker Health ─────────────────────────────────────────────────────────────

@router.get("/execution/broker-health/current")
@inject
async def get_broker_health_current(
    broker_health_svc=Depends(Provide[ApplicationContainer.broker_health_monitor_service]),
) -> dict[str, Any]:
    """Current broker health score and metrics."""
    return await broker_health_svc.get_current()


@router.get("/execution/broker-health/history")
@inject
async def get_broker_health_history(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    broker_health_svc=Depends(Provide[ApplicationContainer.broker_health_monitor_service]),
) -> list[dict[str, Any]]:
    """Broker health score history."""
    return await broker_health_svc.get_history(hours=hours)


@router.get("/execution/broker-health/summary")
@inject
async def get_broker_health_summary(
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    broker_health_svc=Depends(Provide[ApplicationContainer.broker_health_monitor_service]),
) -> dict[str, Any]:
    """Aggregated broker health over a window."""
    return await broker_health_svc.get_summary(hours=hours)


# ── Replay ────────────────────────────────────────────────────────────────────

@router.get("/execution/replay")
@inject
async def list_recent_replays(
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    replay_svc=Depends(Provide[ApplicationContainer.execution_replay_service]),
) -> list[dict[str, Any]]:
    """List recent execution summaries available for replay."""
    return await replay_svc.get_recent_replays(limit=limit)


@router.get("/execution/replay/{signal_id}")
@inject
async def get_replay(
    signal_id: str,
    replay_svc=Depends(Provide[ApplicationContainer.execution_replay_service]),
) -> dict[str, Any]:
    """Full execution replay for a signal_id."""
    result = await replay_svc.get_replay(signal_id)
    return result or {"detail": "not_found"}


# ── Historical Analytics ──────────────────────────────────────────────────────

@router.get("/execution/historical/{window}")
@inject
async def get_historical_window(
    window: str,
    historical_svc=Depends(Provide[ApplicationContainer.execution_historical_service]),
) -> dict[str, Any]:
    """Execution analytics for a named window: 1d, 7d, 30d, 90d, lifetime."""
    return await historical_svc.get_window_stats(window=window)


@router.get("/execution/historical")
@inject
async def get_all_historical_windows(
    historical_svc=Depends(Provide[ApplicationContainer.execution_historical_service]),
) -> dict[str, Any]:
    """Execution analytics for all windows simultaneously."""
    return await historical_svc.get_all_windows()


@router.get("/execution/historical/trend/{metric}")
@inject
async def get_historical_trend(
    metric: str,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    historical_svc=Depends(Provide[ApplicationContainer.execution_historical_service]),
) -> list[dict[str, Any]]:
    """Daily trend for a metric (avg_exec_ms, avg_entry_slip_pct, avg_quality_score)."""
    return await historical_svc.get_trend(metric=metric, days=days)


# ── Dashboard Summary ─────────────────────────────────────────────────────────

@router.get("/execution/dashboard")
@inject
async def get_execution_dashboard(
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    timeline_svc=Depends(Provide[ApplicationContainer.execution_timeline_service]),
    latency_svc=Depends(Provide[ApplicationContainer.execution_latency_service]),
    slippage_svc=Depends(Provide[ApplicationContainer.execution_slippage_service]),
    rejection_svc=Depends(Provide[ApplicationContainer.execution_rejection_service]),
    broker_health_svc=Depends(Provide[ApplicationContainer.broker_health_monitor_service]),
) -> dict[str, Any]:
    """All-in-one execution dashboard for the given time window."""
    import asyncio
    timeline_coro   = timeline_svc.get_recent(limit=10)
    latency_coro    = latency_svc.get_stats(hours=hours)
    slippage_coro   = slippage_svc.get_slippage_stats(hours=hours)
    fill_coro       = slippage_svc.get_fill_quality_stats(hours=hours)
    rejection_coro  = rejection_svc.get_stats(hours=hours)
    health_coro     = broker_health_svc.get_current()

    timeline, latency, slippage, fill, rejections, health = await asyncio.gather(
        timeline_coro, latency_coro, slippage_coro, fill_coro, rejection_coro, health_coro,
        return_exceptions=True,
    )
    return {
        "hours": hours,
        "recent_executions": timeline if not isinstance(timeline, Exception) else [],
        "latency":     latency   if not isinstance(latency, Exception)   else {},
        "slippage":    slippage  if not isinstance(slippage, Exception)  else {},
        "fill_quality": fill     if not isinstance(fill, Exception)      else {},
        "rejections":  rejections if not isinstance(rejections, Exception) else {},
        "broker_health": health  if not isinstance(health, Exception)   else {},
    }
