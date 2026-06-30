"""Phase 25 — Experiment Framework API.

POST   /api/v1/experiments                        — create experiment
GET    /api/v1/experiments                        — list all experiments
GET    /api/v1/experiments/{experiment_id}        — get single experiment
PATCH  /api/v1/experiments/{experiment_id}/status — change status (ACTIVE|PAUSED|COMPLETED|REJECTED)
POST   /api/v1/experiments/{experiment_id}/approve — human approval
PUT    /api/v1/experiments/{experiment_id}/conclusion — write conclusion
GET    /api/v1/experiments/{experiment_id}/validation — statistical analysis
GET    /api/v1/experiments/{experiment_id}/governance  — governance gate check
GET    /api/v1/platform/status                    — platform architecture status
GET    /api/v1/platform/weekly-review             — automated weekly research review
GET    /api/v1/platform/events                    — audit event log
"""

from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from container import ApplicationContainer
from core.application.services.change_governance_service import ChangeGovernanceService
from core.application.services.experiment_service import ExperimentService
from core.application.services.platform_constants import (
    ARCHITECTURE_STATUS,
    CONFIDENCE_VERSION,
    FROZEN_CHANGE_CATEGORIES,
    GOVERNANCE_MIN_TRADES,
    OVERLAY_VERSION,
    RISK_VERSION,
    STRATEGY_VERSION,
    TARGET_VERSION,
)
from core.application.services.weekly_research_review_service import WeeklyResearchReviewService
from core.presentation.api.v1.dependencies.auth import require_authenticated, require_admin
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(tags=["Experiments & Platform"])


# ── Platform Status ───────────────────────────────────────────────────────────

@router.get("/platform/status")
@inject
async def platform_status(
    current_user: CurrentUser = Depends(require_authenticated),
) -> dict[str, Any]:
    """Return the current platform freeze/architecture status and version manifest."""
    return {
        "architecture_status":    ARCHITECTURE_STATUS,
        "is_frozen":              ARCHITECTURE_STATUS == "FROZEN",
        "version_manifest": {
            "strategy_version":   STRATEGY_VERSION,
            "confidence_version": CONFIDENCE_VERSION,
            "overlay_version":    OVERLAY_VERSION,
            "risk_version":       RISK_VERSION,
            "target_version":     TARGET_VERSION,
        },
        "governance_thresholds": {
            "minimum_trades":     GOVERNANCE_MIN_TRADES,
            "required_p_value":   0.05,
            "required_confidence": 0.95,
        },
        "frozen_change_categories": FROZEN_CHANGE_CATEGORIES,
        "evolution_policy": (
            "All changes must pass 7 governance gates: "
            "min_trades, walk_forward, paper_validation, statistical_significance, "
            "rollback_plan, impact_documented, human_approval"
        ),
    }


# ── Weekly Research Review ────────────────────────────────────────────────────

@router.get("/platform/weekly-review")
@inject
async def weekly_review(
    days: int = Query(7, ge=1, le=30),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: WeeklyResearchReviewService = Depends(
        Provide[ApplicationContainer.weekly_research_review_service]
    ),
) -> dict[str, Any]:
    """Generate the automated weekly research review."""
    return await svc.generate(lookback_days=days)


# ── Platform Events ───────────────────────────────────────────────────────────

@router.get("/platform/events")
@inject
async def platform_events(
    limit: int = Query(50, ge=1, le=500),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    events = await svc.list_platform_events(limit=limit)
    return {"count": len(events), "events": events}


# ── Experiment CRUD ───────────────────────────────────────────────────────────

@router.post("/experiments")
@inject
async def create_experiment(
    payload: dict = Body(...),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    """Create a new A/B experiment (starts in DRAFT status)."""
    return await svc.create_experiment(payload)


@router.get("/experiments")
@inject
async def list_experiments(
    status: str | None = Query(None),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    experiments = await svc.list_experiments(status=status)
    return {"count": len(experiments), "experiments": experiments}


@router.get("/experiments/{experiment_id}")
@inject
async def get_experiment(
    experiment_id: str,
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    exp = await svc.get_experiment(experiment_id)
    if exp is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experiment {experiment_id} not found")
    return exp


@router.patch("/experiments/{experiment_id}/status")
@inject
async def update_experiment_status(
    experiment_id: str,
    payload: dict = Body(...),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    """Change experiment status. Payload: {status, notes}"""
    result = await svc.update_status(
        experiment_id,
        new_status=payload["status"],
        actor=current_user.username,
        notes=payload.get("notes"),
    )
    if result is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return result


@router.post("/experiments/{experiment_id}/approve")
@inject
async def approve_experiment(
    experiment_id: str,
    current_user: CurrentUser = Depends(require_admin),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    """Admin: approve an experiment for A/B signal routing."""
    result = await svc.approve_experiment(experiment_id, approved_by=current_user.username)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    return result


@router.put("/experiments/{experiment_id}/conclusion")
@inject
async def set_conclusion(
    experiment_id: str,
    payload: dict = Body(...),
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    """Write the final conclusion for a completed/rejected experiment."""
    await svc.set_conclusion(experiment_id, payload["conclusion"], actor=current_user.username)
    return {"ok": True, "experiment_id": experiment_id.upper()}


# ── Statistical Validation ────────────────────────────────────────────────────

@router.get("/experiments/{experiment_id}/validation")
@inject
async def experiment_validation(
    experiment_id: str,
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ExperimentService = Depends(Provide[ApplicationContainer.experiment_service]),
) -> dict[str, Any]:
    """Run statistical analysis (Wilson CI, Z-test, p-value, recommendation) for an experiment."""
    return await svc.compute_validation(experiment_id)


# ── Change Governance ─────────────────────────────────────────────────────────

@router.get("/experiments/{experiment_id}/governance")
@inject
async def governance_check(
    experiment_id: str,
    current_user: CurrentUser = Depends(require_authenticated),
    svc: ChangeGovernanceService = Depends(
        Provide[ApplicationContainer.change_governance_service]
    ),
) -> dict[str, Any]:
    """Check all 7 governance gates for an experiment. APPROVED = safe to deploy."""
    report = await svc.evaluate(experiment_id)
    return {
        "experiment_id":   report.experiment_id,
        "overall":         report.overall,
        "approved":        report.approved,
        "blocking_gates":  report.blocking_gates,
        "summary":         report.summary,
        "gates": [
            {"gate": g.gate, "passed": g.passed, "detail": g.detail}
            for g in report.gates
        ],
    }
