"""Scanner Intelligence Router — Phase 22 §11/12/13.

Read-only endpoints for scanner heatmaps, market regime, scan replay, and resources.

GET /api/v1/scanner/heatmap/scores       — top scoring symbols
GET /api/v1/scanner/heatmap/oi-buildup   — highest OI buildup
GET /api/v1/scanner/heatmap/trend        — strongest trend symbols
GET /api/v1/scanner/heatmap/volume       — highest volume symbols
GET /api/v1/scanner/heatmap/iv           — highest IV symbols
GET /api/v1/scanner/regime               — latest market regime snapshot
GET /api/v1/scanner/regime/history       — regime history
GET /api/v1/scanner/replay               — list scan snapshots
GET /api/v1/scanner/replay/{id}          — full snapshot
GET /api/v1/scanner/replay/{id}/symbol/{symbol} — symbol drill-down
GET /api/v1/scanner/health               — scanner health stats
GET /api/v1/scanner/resources            — resource monitoring
"""
from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import text

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/scanner", tags=["Scanner Intelligence"])


# ── Heatmaps ─────────────────────────────────────────────────────────────────

@router.get("/heatmap/scores")
@inject
async def heatmap_scores(
    limit: int = Query(20, ge=1, le=100),
    hours: int = Query(4, ge=1, le=48),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Top scoring symbols from recent scan cycles."""
    try:
        from sqlalchemy import text
        # Pull top adjusted_score entries from signal_analytics in last N hours
        sf = scan_metrics_svc._sf
        async with sf() as db:
            r = await db.execute(text("""
                SELECT symbol_name, adjusted_score, confidence, direction,
                       regime, strategy_type, recorded_at
                FROM signal_analytics
                WHERE recorded_at > NOW() - INTERVAL :hrs
                  AND adjusted_score IS NOT NULL
                ORDER BY adjusted_score DESC
                LIMIT :lim
            """), {"hrs": f"{hours} hours", "lim": limit})
            rows = r.mappings().fetchall()
        return {"data": [dict(r) for r in rows], "hours": hours}
    except Exception as exc:
        return {"error": str(exc), "data": []}


@router.get("/heatmap/oi-buildup")
@inject
async def heatmap_oi_buildup(
    limit: int = Query(20, ge=1, le=100),
    hours: int = Query(4, ge=1, le=48),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Symbols with highest positive OI change (long buildup)."""
    try:
        sf = scan_metrics_svc._sf
        async with sf() as db:
            r = await db.execute(text("""
                SELECT symbol_name, oi_change_pct, oi_direction, futures_oi,
                       adjusted_score, recorded_at
                FROM signal_analytics
                WHERE recorded_at > NOW() - INTERVAL :hrs
                  AND oi_change_pct IS NOT NULL
                ORDER BY oi_change_pct DESC
                LIMIT :lim
            """), {"hrs": f"{hours} hours", "lim": limit})
            rows = r.mappings().fetchall()
        return {"data": [dict(r) for r in rows], "hours": hours}
    except Exception as exc:
        return {"error": str(exc), "data": []}


@router.get("/heatmap/trend")
@inject
async def heatmap_trend(
    limit: int = Query(20, ge=1, le=100),
    hours: int = Query(4, ge=1, le=48),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Strongest trend symbols by ADX score."""
    try:
        sf = scan_metrics_svc._sf
        async with sf() as db:
            r = await db.execute(text("""
                SELECT symbol_name, direction, regime, adjusted_score,
                       confidence, recorded_at
                FROM signal_analytics
                WHERE recorded_at > NOW() - INTERVAL :hrs
                  AND regime IN ('TRENDING_BULLISH','TRENDING_BEARISH')
                ORDER BY adjusted_score DESC NULLS LAST
                LIMIT :lim
            """), {"hrs": f"{hours} hours", "lim": limit})
            rows = r.mappings().fetchall()
        return {"data": [dict(r) for r in rows], "hours": hours}
    except Exception as exc:
        return {"error": str(exc), "data": []}


@router.get("/heatmap/volume")
@inject
async def heatmap_volume(
    limit: int = Query(20, ge=1, le=100),
    hours: int = Query(4, ge=1, le=48),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Highest volume symbols from recent scans."""
    try:
        sf = scan_metrics_svc._sf
        async with sf() as db:
            r = await db.execute(text("""
                SELECT sa.symbol_name, sa.adjusted_score, sa.direction,
                       sa.recorded_at
                FROM signal_analytics sa
                WHERE sa.recorded_at > NOW() - INTERVAL :hrs
                ORDER BY sa.adjusted_score DESC NULLS LAST
                LIMIT :lim
            """), {"hrs": f"{hours} hours", "lim": limit})
            rows = r.mappings().fetchall()
        return {"data": [dict(r) for r in rows], "hours": hours}
    except Exception as exc:
        return {"error": str(exc), "data": []}


@router.get("/heatmap/iv")
@inject
async def heatmap_iv(
    limit: int = Query(20, ge=1, le=100),
    hours: int = Query(4, ge=1, le=48),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Symbols with highest IV (option premium expensive)."""
    try:
        sf = scan_metrics_svc._sf
        async with sf() as db:
            r = await db.execute(text("""
                SELECT symbol_name, adjusted_score, direction, regime, recorded_at
                FROM signal_analytics
                WHERE recorded_at > NOW() - INTERVAL :hrs
                  AND regime = 'HIGH_VOLATILITY'
                ORDER BY adjusted_score DESC NULLS LAST
                LIMIT :lim
            """), {"hrs": f"{hours} hours", "lim": limit})
            rows = r.mappings().fetchall()
        return {"data": [dict(r) for r in rows], "hours": hours}
    except Exception as exc:
        return {"error": str(exc), "data": []}


# ── Market Regime ─────────────────────────────────────────────────────────────

@router.get("/regime")
@inject
async def get_regime(
    regime_snapshot_svc=Depends(Provide[ApplicationContainer.market_regime_snapshot_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Latest market regime classification."""
    try:
        snap = await regime_snapshot_svc.get_latest()
        return {"data": snap}
    except Exception as exc:
        return {"error": str(exc), "data": None}


@router.get("/regime/history")
@inject
async def get_regime_history(
    limit: int = Query(50, ge=1, le=200),
    regime_snapshot_svc=Depends(Provide[ApplicationContainer.market_regime_snapshot_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Recent regime classification history."""
    try:
        rows = await regime_snapshot_svc.get_history(limit=limit)
        return {"data": rows, "count": len(rows)}
    except Exception as exc:
        return {"error": str(exc), "data": []}


# ── Scanner Replay ────────────────────────────────────────────────────────────

@router.get("/replay")
@inject
async def list_replay_snapshots(
    limit: int = Query(50, ge=1, le=200),
    scanner_replay_svc=Depends(Provide[ApplicationContainer.scanner_replay_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """List recent scan replay snapshots (summary only)."""
    try:
        rows = await scanner_replay_svc.list_snapshots(limit=limit)
        return {"data": rows, "count": len(rows)}
    except Exception as exc:
        return {"error": str(exc), "data": []}


@router.get("/replay/{snapshot_id}")
@inject
async def get_replay_snapshot(
    snapshot_id: int = Path(..., ge=1),
    scanner_replay_svc=Depends(Provide[ApplicationContainer.scanner_replay_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Full scan replay snapshot including all symbol results."""
    try:
        snap = await scanner_replay_svc.get_snapshot(snapshot_id)
        if snap is None:
            return {"error": "not_found", "data": None}
        return {"data": snap}
    except Exception as exc:
        return {"error": str(exc), "data": None}


@router.get("/replay/{snapshot_id}/symbol/{symbol}")
@inject
async def get_replay_symbol(
    snapshot_id: int = Path(..., ge=1),
    symbol: str = Path(...),
    scanner_replay_svc=Depends(Provide[ApplicationContainer.scanner_replay_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Symbol-level drill-down within a replay snapshot."""
    try:
        result = await scanner_replay_svc.get_symbol_result(snapshot_id, symbol)
        if result is None:
            return {"error": "not_found", "data": None}
        return {"data": result}
    except Exception as exc:
        return {"error": str(exc), "data": None}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
@inject
async def get_scanner_health(
    hours: int = Query(24, ge=1, le=168),
    scan_metrics_svc=Depends(Provide[ApplicationContainer.scan_metrics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Scanner health stats: rolling latency, acceptance rate, health score."""
    try:
        summary = await scan_metrics_svc.get_summary(hours=hours)
        recent  = await scan_metrics_svc.get_recent(limit=5)
        return {
            "summary": summary,
            "last_5_cycles": recent,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Resources ─────────────────────────────────────────────────────────────────

@router.get("/resources")
@inject
async def get_resources(
    resource_monitor_svc=Depends(Provide[ApplicationContainer.resource_monitor_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Current system resource usage (CPU, memory, Redis, DB pool)."""
    try:
        cached = await resource_monitor_svc.get_cached()
        if cached:
            return {"data": cached, "source": "cache"}
        # Collect fresh if no cache
        snap = await resource_monitor_svc.collect()
        return {"data": snap, "source": "live"}
    except Exception as exc:
        return {"error": str(exc), "data": None}
