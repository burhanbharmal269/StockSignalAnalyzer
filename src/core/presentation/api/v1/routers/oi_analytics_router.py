"""OI Analytics Router — Phase 21.1 Part 17.

Read-only endpoints exposing Futures OI intelligence. All endpoints are
GET only and have zero write effects on live trading.

GET /api/v1/oi/current/{symbol}          — live OI state for one symbol
GET /api/v1/oi/history/{symbol}          — historical OI snapshots
GET /api/v1/oi/regime/{symbol}           — OI regime + distribution
GET /api/v1/oi/quality/{symbol}          — OI quality tier + score
GET /api/v1/oi/health                    — all-symbol health summary
GET /api/v1/oi/breadth                   — market-wide OI breadth
GET /api/v1/oi/anomalies                 — active OI anomalies
GET /api/v1/oi/features                  — feature registry rankings
GET /api/v1/oi/failures                  — OI failure pattern analysis
GET /api/v1/oi/tmi-by-regime             — TMI metrics by OI regime
GET /api/v1/oi/walk-forward              — walk-forward regime performance
GET /api/v1/oi/metrics                   — Prometheus-style counters
"""
from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/oi", tags=["OI Analytics"])


# ── Current OI state ──────────────────────────────────────────────────────────

@router.get("/current/{symbol}")
@inject
async def get_current_oi(
    symbol: str,
    futures_oi_svc=Depends(Provide[ApplicationContainer.futures_oi_service]),
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Live Futures OI state + quality + regime for one symbol."""
    snap = futures_oi_svc.get_cached(symbol.upper())
    if snap is None:
        return {"symbol": symbol.upper(), "available": False}
    return {
        "symbol":        snap.underlying,
        "tradingsymbol": snap.tradingsymbol,
        "expiry":        str(snap.expiry),
        "last_price":    snap.last_price,
        "oi":            snap.oi,
        "oi_change":     snap.oi_change,
        "oi_change_pct": snap.oi_change_pct,
        "oi_direction":  snap.oi_direction,
        "timestamp":     snap.timestamp.isoformat(),
        "quality":       oi_svc.get_quality(snap.underlying),
        "regime":        oi_svc.get_regime(snap.underlying),
        "available":     True,
    }


# ── Historical OI ─────────────────────────────────────────────────────────────

@router.get("/history/{symbol}")
@inject
async def get_oi_history(
    symbol: str,
    hours: int = Query(default=24, ge=1, le=720),
    oi_repo=Depends(Provide[ApplicationContainer.oi_history_repository]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Historical OI snapshots for a symbol (up to 30 days)."""
    rows = await oi_repo.get_history(symbol.upper(), hours=hours)
    return {"symbol": symbol.upper(), "hours": hours, "count": len(rows), "history": rows}


# ── OI Regime ─────────────────────────────────────────────────────────────────

@router.get("/regime/{symbol}")
@inject
async def get_oi_regime(
    symbol: str,
    days: int = Query(default=30, ge=1, le=90),
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    oi_repo=Depends(Provide[ApplicationContainer.oi_history_repository]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Current regime + historical distribution for a symbol."""
    distribution = await oi_repo.get_regime_distribution(symbol.upper(), days=days)
    return {
        "symbol":       symbol.upper(),
        "current":      oi_svc.get_regime(symbol.upper()),
        "period_days":  days,
        "distribution": distribution,
    }


# ── OI Quality ────────────────────────────────────────────────────────────────

@router.get("/quality/{symbol}")
@inject
async def get_oi_quality(
    symbol: str,
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """OI quality tier and numeric score for a symbol."""
    return {"symbol": symbol.upper(), **oi_svc.get_quality(symbol.upper())}


# ── Symbol health ─────────────────────────────────────────────────────────────

@router.get("/health")
@inject
async def get_symbol_health(
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Health report for all tracked symbols (Part 10)."""
    all_health = oi_svc.get_all_health()
    coverage = oi_svc.get_coverage_summary()
    return {
        "coverage":      coverage,
        "symbols":       all_health,
        "symbol_count":  len(all_health),
    }


# ── Market breadth ────────────────────────────────────────────────────────────

@router.get("/breadth")
@inject
async def get_market_breadth(
    hours: int = Query(default=1, ge=1, le=24),
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    oi_repo=Depends(Provide[ApplicationContainer.oi_history_repository]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Live OI-based market breadth (Part 9)."""
    live = oi_svc.get_market_breadth_oi()
    top_inc, top_dec = await oi_repo.get_top_oi_movers(limit=10, hours=hours)
    return {
        "live_breadth":    live,
        "top_increases":   top_inc,
        "top_decreases":   top_dec,
        "hours":           hours,
    }


# ── Active anomalies ──────────────────────────────────────────────────────────

@router.get("/anomalies")
@inject
async def get_anomalies(
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """All symbols currently in an anomalous OI state (Part 12)."""
    anomalies = oi_svc.get_anomalies()
    return {"count": len(anomalies), "anomalies": anomalies}


# ── Feature registry ──────────────────────────────────────────────────────────

@router.get("/features")
@inject
async def get_features(
    category: str | None = Query(default=None),
    ranked: bool = Query(default=True),
    feature_reg=Depends(Provide[ApplicationContainer.feature_registry]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Feature registry — all features or filtered by category (Part 22)."""
    if category:
        features = feature_reg.get_by_category(category)
    elif ranked:
        features = feature_reg.get_ranked()
    else:
        features = feature_reg.get_all()
    degraded = feature_reg.get_degraded()
    return {
        "count":    len(features),
        "features": features,
        "degraded": len(degraded),
        "degraded_features": [f["name"] for f in degraded],
    }


# ── Failure attribution ───────────────────────────────────────────────────────

@router.get("/failures")
@inject
async def get_failure_patterns(
    days: int = Query(default=30, ge=7, le=180),
    failure_svc=Depends(Provide[ApplicationContainer.failure_attribution_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """OI conditions at the time of failing trades (Part 5)."""
    return await failure_svc.get_oi_failure_patterns(days=days)


@router.get("/tmi-by-regime")
@inject
async def get_tmi_by_regime(
    days: int = Query(default=30, ge=7, le=180),
    failure_svc=Depends(Provide[ApplicationContainer.failure_attribution_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """TMI metrics (capture ratio, MFE, surrender) split by OI regime (Part 4)."""
    return await failure_svc.get_tmi_by_oi_regime(days=days)


@router.get("/walk-forward")
@inject
async def get_walk_forward(
    days: int = Query(default=90, ge=30, le=365),
    failure_svc=Depends(Provide[ApplicationContainer.failure_attribution_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Walk-forward performance by OI regime with research recommendations (Part 8)."""
    return await failure_svc.get_regime_walk_forward(days=days)


# ── Win rate by regime ────────────────────────────────────────────────────────

@router.get("/win-rate-by-regime")
@inject
async def get_win_rate_by_regime(
    days: int = Query(default=90, ge=7, le=365),
    oi_repo=Depends(Provide[ApplicationContainer.oi_history_repository]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Win rate, MFE, capture ratio — split by OI regime at signal time."""
    rows = await oi_repo.get_win_rate_by_regime(days=days)
    return {"period_days": days, "by_regime": rows}


# ── Prometheus metrics ────────────────────────────────────────────────────────

@router.get("/metrics")
@inject
async def get_oi_metrics(
    oi_svc=Depends(Provide[ApplicationContainer.oi_analytics_service]),
    _user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Internal counters for Grafana/Prometheus integration (Part 18)."""
    return oi_svc.get_metrics()
