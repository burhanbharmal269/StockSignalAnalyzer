"""Platform Router — Phase 24 Operations.

GET  /api/v1/platform/readiness            — unified platform health
GET  /api/v1/platform/readiness/run        — trigger immediate pre-market check

GET  /api/v1/platform/incidents            — list incidents (filter by type/severity)
POST /api/v1/platform/incidents            — create incident
GET  /api/v1/platform/incidents/summary    — aggregate summary
GET  /api/v1/platform/incidents/{id}       — single incident
POST /api/v1/platform/incidents/{id}/resolve — resolve incident

GET  /api/v1/platform/scan-metrics         — recent scan cycle metrics
GET  /api/v1/platform/scan-metrics/summary — aggregate summary (last N hours)

GET  /api/v1/platform/pre-market           — latest pre-market check
GET  /api/v1/platform/pre-market/history   — history (last 30 days)
"""

from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.incident_service import IncidentService
from core.application.services.platform_readiness_service import PlatformReadinessService
from core.application.services.pre_market_checklist_service import PreMarketChecklistService
from core.application.services.scan_metrics_service import ScanMetricsService
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/platform", tags=["Platform"])


# ── Readiness ─────────────────────────────────────────────────────────────────

@router.get("/readiness", summary="Unified platform readiness across all components")
@inject
async def get_platform_readiness(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: PlatformReadinessService = Depends(
        Provide[ApplicationContainer.platform_readiness_service]
    ),
) -> dict[str, Any]:
    return await svc.get_readiness()


@router.get(
    "/readiness/run",
    summary="Run pre-market checklist immediately and return result",
)
@inject
async def run_pre_market_check(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: PreMarketChecklistService = Depends(
        Provide[ApplicationContainer.pre_market_checklist_service]
    ),
) -> dict[str, Any]:
    return await svc.run_now()


# ── Incidents ─────────────────────────────────────────────────────────────────

@router.get("/incidents/summary", summary="Incident aggregate summary")
@inject
async def get_incident_summary(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: IncidentService = Depends(Provide[ApplicationContainer.incident_service]),
) -> dict[str, Any]:
    return await svc.get_summary()


@router.get("/incidents", summary="List incidents")
@inject
async def list_incidents(
    _user: CurrentUser = Depends(require_no_force_change),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    incident_type: str | None = Query(None),
    severity: str | None = Query(None),
    unresolved_only: bool = Query(False),
    svc: IncidentService = Depends(Provide[ApplicationContainer.incident_service]),
) -> dict[str, Any]:
    return await svc.list_incidents(
        limit=limit,
        offset=offset,
        incident_type=incident_type,
        severity=severity,
        unresolved_only=unresolved_only,
    )


@router.post("/incidents", summary="Create a new incident", status_code=201)
@inject
async def create_incident(
    body: dict[str, Any],
    _user: CurrentUser = Depends(require_no_force_change),
    svc: IncidentService = Depends(Provide[ApplicationContainer.incident_service]),
) -> dict[str, Any]:
    return await svc.create(
        incident_type=body["incident_type"],
        severity=body["severity"],
        title=body["title"],
        root_cause=body.get("root_cause"),
        impact=body.get("impact"),
        recovery_actions=body.get("recovery_actions"),
    )


@router.get("/incidents/{incident_id}", summary="Get single incident")
@inject
async def get_incident(
    incident_id: int,
    _user: CurrentUser = Depends(require_no_force_change),
    svc: IncidentService = Depends(Provide[ApplicationContainer.incident_service]),
) -> dict[str, Any]:
    return await svc.get(incident_id)


@router.post("/incidents/{incident_id}/resolve", summary="Resolve an incident")
@inject
async def resolve_incident(
    incident_id: int,
    body: dict[str, Any],
    _user: CurrentUser = Depends(require_no_force_change),
    svc: IncidentService = Depends(Provide[ApplicationContainer.incident_service]),
) -> dict[str, Any]:
    return await svc.resolve(
        incident_id,
        resolution=body["resolution"],
        root_cause=body.get("root_cause"),
        recovery_actions=body.get("recovery_actions"),
    )


# ── Scan Metrics ──────────────────────────────────────────────────────────────

@router.get("/scan-metrics", summary="Recent scan cycle metrics")
@inject
async def get_scan_metrics(
    _user: CurrentUser = Depends(require_no_force_change),
    limit: int = Query(50, ge=1, le=200),
    svc: ScanMetricsService = Depends(Provide[ApplicationContainer.scan_metrics_service]),
) -> list[dict[str, Any]]:
    return await svc.get_recent(limit=limit)


@router.get("/scan-metrics/summary", summary="Aggregated scan metrics over last N hours")
@inject
async def get_scan_metrics_summary(
    _user: CurrentUser = Depends(require_no_force_change),
    hours: int = Query(24, ge=1, le=168),
    svc: ScanMetricsService = Depends(Provide[ApplicationContainer.scan_metrics_service]),
) -> dict[str, Any]:
    return await svc.get_summary(hours=hours)


# ── Pre-Market Checklist ──────────────────────────────────────────────────────

@router.get("/pre-market", summary="Latest pre-market checklist result")
@inject
async def get_pre_market_latest(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: PreMarketChecklistService = Depends(
        Provide[ApplicationContainer.pre_market_checklist_service]
    ),
) -> dict[str, Any] | None:
    return await svc.get_latest()


@router.get("/pre-market/history", summary="Pre-market check history")
@inject
async def get_pre_market_history(
    _user: CurrentUser = Depends(require_no_force_change),
    limit: int = Query(30, ge=1, le=90),
    svc: PreMarketChecklistService = Depends(
        Provide[ApplicationContainer.pre_market_checklist_service]
    ),
) -> list[dict[str, Any]]:
    return await svc.get_history(limit=limit)
