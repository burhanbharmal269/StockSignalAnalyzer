"""Validation Router — Phase 22.

All endpoints are READ-ONLY. Nothing here changes strategy, weights, thresholds,
overlays, or any trading logic. This phase is MEASURE, VALIDATE, REPORT only.

GET  /api/v1/validation/readiness          — §1 deployment readiness score (0-100, 5 categories)
GET  /api/v1/validation/milestones         — §2 milestone gates at 50/200/500/1000 trades
GET  /api/v1/validation/confidence         — §3 Wilson CI for win rate + expectancy CI
GET  /api/v1/validation/overlay            — §4 per-overlay statistical validation
GET  /api/v1/validation/components         — §5 component discriminative power
GET  /api/v1/validation/bugs               — §8 silent failure pattern detection
GET  /api/v1/validation/drift              — §9 production drift vs baseline
GET  /api/v1/validation/go-no-go           — §10 4-gate deployment readiness
GET  /api/v1/validation/report/summary     — §11 lightweight summary report
GET  /api/v1/validation/report/full        — §11 full weekly validation report
"""

from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.bug_detection_service import BugDetectionService
from core.application.services.deployment_readiness_service import DeploymentReadinessService
from core.application.services.go_no_go_service import GoNoGoService
from core.application.services.production_drift_service import ProductionDriftService
from core.application.services.statistical_validation_service import StatisticalValidationService
from core.application.services.validation_report_service import ValidationReportService
from core.presentation.api.dependencies import CurrentUser, require_no_force_change

router = APIRouter(prefix="/validation", tags=["Validation"])


# ── §1 Deployment Readiness ───────────────────────────────────────────────────

@router.get("/readiness", summary="Deployment readiness score (0-100)")
@inject
async def get_readiness(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: DeploymentReadinessService = Depends(Provide[ApplicationContainer.deployment_readiness_service]),
) -> dict[str, Any]:
    """
    Returns a 0-100 score across 5 weighted categories:
    Infrastructure (20), Strategy (25), Execution (15), Risk (20), Data Quality (20).
    Tiers: NOT_READY / LIMITED / READY_FOR_SMALL_CAPITAL / READY_FOR_SCALING.
    """
    return await svc.get_readiness_score()


# ── §2 Validation Milestones ──────────────────────────────────────────────────

@router.get("/milestones", summary="Validation milestones at 50/200/500/1000 trades")
@inject
async def get_milestones(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: StatisticalValidationService = Depends(Provide[ApplicationContainer.statistical_validation_service]),
) -> dict[str, Any]:
    """
    Returns pass/fail status for each trade-count milestone with win rate,
    profit factor, and expectancy checks.
    """
    return await svc.get_validation_milestones()


# ── §3 Confidence Intervals ───────────────────────────────────────────────────

@router.get("/confidence", summary="Wilson CI for win rate and expectancy CI")
@inject
async def get_confidence_intervals(
    lookback_days: int = Query(default=90, ge=7, le=365, description="Lookback window in days"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: StatisticalValidationService = Depends(Provide[ApplicationContainer.statistical_validation_service]),
) -> dict[str, Any]:
    """
    Returns 95% Wilson score CI for win rate and normal CI for expectancy,
    stratified by execution grade and regime.
    """
    return await svc.get_confidence_intervals(lookback_days=lookback_days)


# ── §4 Overlay Validation ─────────────────────────────────────────────────────

@router.get("/overlay", summary="Per-overlay statistical validation")
@inject
async def get_overlay_validation(
    lookback_days: int = Query(default=60, ge=7, le=365, description="Lookback window in days"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: StatisticalValidationService = Depends(Provide[ApplicationContainer.statistical_validation_service]),
) -> dict[str, Any]:
    """
    For each overlay: fired vs not-fired win rate, recommendation (KEEP/REDUCE/REMOVE).
    Uses LIKE pattern on decision_trace_json to detect overlay application.
    """
    return await svc.get_overlay_validation(lookback_days=lookback_days)


# ── §5 Component Validation ───────────────────────────────────────────────────

@router.get("/components", summary="Component discriminative power")
@inject
async def get_component_validation(
    lookback_days: int = Query(default=60, ge=7, le=365, description="Lookback window in days"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: StatisticalValidationService = Depends(Provide[ApplicationContainer.statistical_validation_service]),
) -> dict[str, Any]:
    """
    For each scoring component: win rate in HIGH (≥70) vs LOW (≤30) buckets.
    Discriminative power = win_rate_high - win_rate_low.
    """
    return await svc.get_component_validation(lookback_days=lookback_days)


# ── §8 Bug Detection ──────────────────────────────────────────────────────────

@router.get("/bugs", summary="Silent failure pattern detection")
@inject
async def get_bug_detection(
    sample_n: int = Query(default=100, ge=20, le=500, description="Number of recent signals to inspect"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: BugDetectionService = Depends(Provide[ApplicationContainer.bug_detection_service]),
) -> dict[str, Any]:
    """
    Checks 9 silent-failure patterns: confidence identical, overlay never applied,
    event calendar empty, MTF always neutral, grade always D, data quality constant,
    acceptance rate too low, scanner idle, position size always zero.
    """
    return await svc.run_all_checks(sample_n=sample_n)


# ── §9 Production Drift ───────────────────────────────────────────────────────

@router.get("/drift", summary="Production drift vs baseline period")
@inject
async def get_drift(
    ref_days: int = Query(default=30, ge=7, le=90, description="Reference window length (days)"),
    cmp_days: int = Query(default=7,  ge=1, le=30, description="Comparison window length (days)"),
    gap_days: int = Query(default=0,  ge=0, le=14, description="Gap between periods (days)"),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: ProductionDriftService = Depends(Provide[ApplicationContainer.production_drift_service]),
) -> dict[str, Any]:
    """
    Compares win rate, acceptance rate, confidence, score, grades, and PnL
    between a reference period and a recent comparison period using z-tests.
    """
    return await svc.get_drift_report(ref_days=ref_days, cmp_days=cmp_days, gap_days=gap_days)


# ── §10 Go/No-Go ──────────────────────────────────────────────────────────────

@router.get("/go-no-go", summary="4-gate deployment readiness decision")
@inject
async def get_go_no_go(
    _user: CurrentUser = Depends(require_no_force_change),
    readiness_svc: DeploymentReadinessService = Depends(Provide[ApplicationContainer.deployment_readiness_service]),
    go_no_go_svc: GoNoGoService = Depends(Provide[ApplicationContainer.go_no_go_service]),
) -> dict[str, Any]:
    """
    Evaluates 4 deployment gates with human-readable explanations.
    Fetches current readiness score to feed into gate criteria.
    Gates: Paper(≥40), 1-lot(≥65,n≥50,pf≥1.1,wr≥45%), 2-lot(≥75,n≥200,...), Scale(≥85,n≥500,...).
    """
    readiness = await readiness_svc.get_readiness_score()
    return await go_no_go_svc.get_go_no_go(readiness_score=readiness.get("total_score"))


# ── §11 Validation Reports ────────────────────────────────────────────────────

@router.get("/report/summary", summary="Lightweight validation summary")
@inject
async def get_summary_report(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: ValidationReportService = Depends(Provide[ApplicationContainer.validation_report_service]),
) -> dict[str, Any]:
    """
    Lightweight report: readiness + go/no-go + bug detection only.
    Suitable for dashboard health widgets.
    """
    return await svc.get_summary_report()


@router.get("/report/full", summary="Full weekly validation report")
@inject
async def get_full_report(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: ValidationReportService = Depends(Provide[ApplicationContainer.validation_report_service]),
) -> dict[str, Any]:
    """
    Full validation report: all 7 sections including CI, overlay/component
    validation, drift analysis, and go/no-go. May be slow on large datasets.
    """
    return await svc.get_full_report()
