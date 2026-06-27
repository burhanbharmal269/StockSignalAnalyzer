"""Research Router — Phase 23.

All endpoints are READ-ONLY.  Nothing here modifies strategy, thresholds,
weights, overlays, or any trading logic.

GET  /api/v1/research/health                       — §6  strategy health score (0-100)
GET  /api/v1/research/cohorts/{dimension}          — §3  per-dimension cohort stats
GET  /api/v1/research/cohorts                      — §3  all-dimension cohort summaries
GET  /api/v1/research/cube                         — §4  multi-dimensional cube query
GET  /api/v1/research/recommendations              — §8  evidence-driven recommendations
POST /api/v1/research/freeze-check                 — §9  architecture freeze gate
GET  /api/v1/research/live-vs-paper                — §10 live vs paper comparison
GET  /api/v1/research/report/weekly/latest         — §11 latest weekly report (JSON)
GET  /api/v1/research/report/weekly/generate       — §11 generate + persist new weekly report
GET  /api/v1/research/report/weekly/history        — §11 list of all weekly reports
GET  /api/v1/research/report/weekly/csv            — §11 latest report as CSV download
GET  /api/v1/research/dimensions                   — list of available cube dimensions
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse

from container import ApplicationContainer
from core.application.services.cohort_engine_service import CohortEngineService
from core.application.services.live_validation_service import LiveValidationService
from core.application.services.recommendation_engine_service import RecommendationEngineService
from core.application.services.research_cube_service import ResearchCubeService
from core.application.services.strategy_health_service import StrategyHealthService
from core.application.services.weekly_research_service import WeeklyResearchService
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/research", tags=["Research"])


# ── §6 Strategy Health ────────────────────────────────────────────────────────

@router.get("/health", summary="Platform health score 0-100 across 8 categories")
@inject
async def get_health(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: StrategyHealthService = Depends(Provide[ApplicationContainer.strategy_health_service]),
) -> Any:
    return await svc.get_health_score()


# ── §3 Cohort Engine ──────────────────────────────────────────────────────────

@router.get("/cohorts", summary="All-dimension cohort summaries (top 10 per dimension)")
@inject
async def get_all_cohorts(
    min_trades: int = Query(5, ge=1, le=100),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: CohortEngineService = Depends(Provide[ApplicationContainer.cohort_engine_service]),
) -> Any:
    return await svc.get_all_cohort_summaries(min_trades=min_trades)


@router.get("/cohorts/{dimension}", summary="Per-dimension cohort stats")
@inject
async def get_cohort_dimension(
    dimension: str,
    min_trades: int = Query(5, ge=1, le=100),
    days_back: int | None = Query(None, ge=1, le=365),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: CohortEngineService = Depends(Provide[ApplicationContainer.cohort_engine_service]),
) -> Any:
    return await svc.get_cohort_stats(dimension, min_trades=min_trades, days_back=days_back)


# ── §4 Research Cube ──────────────────────────────────────────────────────────

@router.get("/cube", summary="Multi-dimensional research cube (up to 3 dimensions)")
@inject
async def query_cube(
    dimensions: Annotated[list[str], Query()] = ["score_bucket", "regime"],
    min_trades: int = Query(5, ge=1, le=100),
    days_back: int | None = Query(None, ge=1, le=365),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: ResearchCubeService = Depends(Provide[ApplicationContainer.research_cube_service]),
) -> Any:
    return await svc.query(
        dimensions=dimensions,
        min_trades=min_trades,
        days_back=days_back,
    )


@router.get("/dimensions", summary="List of available research cube dimensions")
@inject
async def get_dimensions(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: ResearchCubeService = Depends(Provide[ApplicationContainer.research_cube_service]),
) -> Any:
    return {"dimensions": await svc.get_available_dimensions()}


# ── §8 Recommendation Engine ──────────────────────────────────────────────────

@router.get("/recommendations", summary="Evidence-driven research recommendations")
@inject
async def get_recommendations(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: RecommendationEngineService = Depends(
        Provide[ApplicationContainer.recommendation_engine_service]
    ),
) -> Any:
    return await svc.generate_recommendations()


# ── §9 Architecture Freeze Gate ───────────────────────────────────────────────

@router.post("/freeze-check", summary="Architecture freeze gate — check if strategy modification is allowed")
@inject
async def check_freeze(
    proposed_change: str = Body(..., embed=True),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: RecommendationEngineService = Depends(
        Provide[ApplicationContainer.recommendation_engine_service]
    ),
) -> Any:
    return await svc.get_frozen_policy_response(proposed_change)


# ── §10 Live vs Paper ─────────────────────────────────────────────────────────

@router.get("/live-vs-paper", summary="Live vs paper trading performance comparison")
@inject
async def get_live_vs_paper(
    days_back: int = Query(90, ge=7, le=365),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: LiveValidationService = Depends(Provide[ApplicationContainer.live_validation_service]),
) -> Any:
    return await svc.get_comparison(days_back=days_back)


# ── §11 Weekly Report ─────────────────────────────────────────────────────────

@router.get("/report/weekly/latest", summary="Latest persisted weekly research report (JSON)")
@inject
async def get_weekly_latest(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: WeeklyResearchService = Depends(Provide[ApplicationContainer.weekly_research_service]),
) -> Any:
    report = await svc.get_latest_report()
    if report is None:
        return {"message": "No weekly report available. Call /generate to create one."}
    return report


@router.get("/report/weekly/generate", summary="Generate and persist a new weekly report")
@inject
async def generate_weekly_report(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: WeeklyResearchService = Depends(Provide[ApplicationContainer.weekly_research_service]),
) -> Any:
    return await svc.generate_weekly_report()


@router.get("/report/weekly/history", summary="List of all stored weekly report summaries")
@inject
async def get_weekly_history(
    limit: int = Query(12, ge=1, le=52),
    _user: CurrentUser = Depends(require_no_force_change),
    svc: WeeklyResearchService = Depends(Provide[ApplicationContainer.weekly_research_service]),
) -> Any:
    return await svc.get_all_reports(limit=limit)


@router.get("/report/weekly/csv", summary="Latest weekly report cohort rankings as CSV download")
@inject
async def download_weekly_csv(
    _user: CurrentUser = Depends(require_no_force_change),
    svc: WeeklyResearchService = Depends(Provide[ApplicationContainer.weekly_research_service]),
) -> Any:
    report = await svc.get_latest_report()
    if not report:
        return {"message": "No report available. Call /generate first."}

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    writer.writerow([
        "dimension", "cohort", "position",
        "trade_count", "win_rate", "profit_factor",
        "expectancy", "sharpe", "avg_score", "avg_confidence",
    ])

    rankings = report.get("cohort_rankings", {})
    for dim_key, dim_data in rankings.items():
        for position, rows in [("top", dim_data.get("top", [])),
                                ("bottom", dim_data.get("bottom", []))]:
            for row in rows:
                writer.writerow([
                    dim_key,
                    row.get("cohort"),
                    position,
                    row.get("trade_count"),
                    row.get("win_rate"),
                    row.get("profit_factor"),
                    row.get("expectancy"),
                    row.get("sharpe"),
                    row.get("avg_score"),
                    row.get("avg_confidence"),
                ])

    buf.seek(0)
    week_label = report.get("week_start", "latest").replace("-", "")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=research_{week_label}.csv"},
    )
