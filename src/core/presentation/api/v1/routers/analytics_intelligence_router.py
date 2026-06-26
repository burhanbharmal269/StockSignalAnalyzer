"""Analytics Intelligence Router — Phase 19 + 20.5 + 20.6 + 21.2

All endpoints are read-only analytics. Nothing here changes live strategy,
thresholds, weights, or signal generation.

GET  /api/v1/analytics/portfolio/dashboard        — Phase 19 portfolio dashboard
GET  /api/v1/analytics/portfolio/heat             — live portfolio heat
GET  /api/v1/analytics/portfolio/risk-of-ruin     — drawdown and RoR ladder
GET  /api/v1/analytics/portfolio/success-criteria — institutional readiness (SC1-SC11)

POST /api/v1/analytics/post-trade/enrich          — trigger attribution backfill
GET  /api/v1/analytics/post-trade/summary         — failure/success attribution summary
GET  /api/v1/analytics/journey                    — MFE/MAE lifecycle profile
GET  /api/v1/analytics/stops                      — stop timing distribution
GET  /api/v1/analytics/recovery                   — recovery analysis post-stop

GET  /api/v1/analytics/components                 — component attribution (per-scorer)
GET  /api/v1/analytics/gates                      — gate effectiveness report
GET  /api/v1/analytics/recommendations            — evidence-based strategy recommendations

GET  /api/v1/analytics/cohorts                    — trade cohort performance table
GET  /api/v1/analytics/edges                      — multi-dimensional edge discovery
GET  /api/v1/analytics/clusters/loss              — loss co-occurrence clusters
GET  /api/v1/analytics/clusters/winners           — winner pattern clusters

GET  /api/v1/analytics/replay/{signal_id}         — lifecycle event timeline for one signal
POST /api/v1/analytics/replay/backfill            — trigger replay backfill
GET  /api/v1/analytics/replay/coverage            — replay coverage stats

GET  /api/v1/analytics/operator/status            — live scanner status panel

GET  /api/v1/analytics/research/dashboard         — aggregated research intelligence
GET  /api/v1/analytics/intelligence/weekly        — weekly intelligence report

Phase 21.2 — Overlay Effectiveness (§4-§8, §15):
GET  /api/v1/analytics/overlay/effectiveness/{overlay_name}  — §4 named overlay: fired vs baseline
GET  /api/v1/analytics/overlay/events                        — §5 event overlay: with vs no event
GET  /api/v1/analytics/overlay/regime-stability              — §6 STABLE/TRANSITION/UNSTABLE breakdown
GET  /api/v1/analytics/overlay/execution-quality             — §7 grade A/B/C/D win-rate monotonicity
GET  /api/v1/analytics/overlay/milestones                    — §15 auto-evaluate at 200/500/1000 trades
"""

from __future__ import annotations

from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.component_attribution_service import ComponentAttributionService
from core.application.services.edge_discovery_service import EdgeDiscoveryService
from core.application.services.loss_cluster_service import LossClusterService
from core.application.services.operator_observability_service import OperatorObservabilityService
from core.application.services.overlay_effectiveness_service import OverlayEffectivenessService
from core.application.services.portfolio_intelligence_service import PortfolioIntelligenceService
from core.application.services.post_trade_intelligence_service import PostTradeIntelligenceService
from core.application.services.research_dashboard_service import ResearchDashboardService
from core.application.services.strategy_evolution_service import StrategyEvolutionService
from core.application.services.trade_cohort_service import TradeCohortService
from core.application.services.trade_journey_service import TradeJourneyService
from core.application.services.trade_replay_service import TradeReplayService
from core.application.services.weekly_intelligence_report_service import WeeklyIntelligenceReportService
from core.presentation.api.v1.dependencies.auth import require_authenticated, require_admin
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics Intelligence"])


# ── Phase 19 — Portfolio Intelligence ─────────────────────────────────────────

@router.get("/portfolio/dashboard", summary="Full portfolio intelligence dashboard")
@inject
async def get_portfolio_dashboard(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: PortfolioIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.portfolio_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.get_portfolio_dashboard()


@router.get("/portfolio/heat", summary="Current portfolio heat (open positions)")
@inject
async def get_portfolio_heat(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: PortfolioIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.portfolio_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.get_portfolio_heat()


@router.get("/portfolio/risk-of-ruin", summary="Drawdown ladder and risk of ruin estimate")
@inject
async def get_risk_of_ruin(
    lookback_days: int = Query(90, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: PortfolioIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.portfolio_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.get_risk_of_ruin(lookback_days=lookback_days)


@router.get("/portfolio/success-criteria", summary="Institutional readiness check (SC1-SC11)")
@inject
async def get_success_criteria(
    lookback_days: int = Query(30, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: PortfolioIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.portfolio_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.get_success_criteria_status(lookback_days=lookback_days)


# ── Phase 20.5 — Post-Trade Intelligence ──────────────────────────────────────

@router.post("/post-trade/enrich", summary="Trigger post-trade attribution backfill (admin)")
@inject
async def enrich_unattributed(
    limit: int = Query(200, ge=1, le=1000),
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    svc: PostTradeIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.post_trade_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.enrich_unattributed(limit=limit)


@router.get("/post-trade/summary", summary="Attribution summary: failure/success reasons")
@inject
async def get_attribution_summary(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: PostTradeIntelligenceService = Depends(  # noqa: B008
        Provide[ApplicationContainer.post_trade_intelligence_service]
    ),
) -> dict[str, Any]:
    return await svc.get_attribution_summary(lookback_days=lookback_days)


@router.get("/journey", summary="MFE/MAE trade journey profile")
@inject
async def get_journey_profile(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeJourneyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_journey_service]
    ),
) -> dict[str, Any]:
    return await svc.get_entry_exit_summary(lookback_days=lookback_days)


@router.get("/stops", summary="Stop timing distribution (IMMEDIATE/EARLY/MEDIUM/LATE)")
@inject
async def get_stop_distribution(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeJourneyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_journey_service]
    ),
) -> dict[str, Any]:
    return await svc.get_stop_distribution_report(lookback_days=lookback_days)


@router.get("/recovery", summary="Would-have-recovered analysis post stop-out")
@inject
async def get_recovery_analysis(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeJourneyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_journey_service]
    ),
) -> dict[str, Any]:
    return await svc.get_recovery_analysis(lookback_days=lookback_days)


@router.get("/components", summary="Component attribution: per-scorer winner vs loser analysis")
@inject
async def get_component_performance(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: ComponentAttributionService = Depends(  # noqa: B008
        Provide[ApplicationContainer.component_attribution_service]
    ),
) -> dict[str, Any]:
    perf = await svc.get_component_performance(lookback_days=lookback_days)
    breakdown = await svc.get_regime_component_breakdown(lookback_days=lookback_days)
    return {"component_performance": perf, "regime_breakdown": breakdown}


@router.get("/gates", summary="Gate effectiveness: pass/fail rate vs outcome quality")
@inject
async def get_gate_effectiveness(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: ComponentAttributionService = Depends(  # noqa: B008
        Provide[ApplicationContainer.component_attribution_service]
    ),
) -> dict[str, Any]:
    return await svc.get_gate_effectiveness(lookback_days=lookback_days)


@router.get("/recommendations", summary="Evidence-based recommendations (read-only, never auto-applied)")
@inject
async def get_recommendations(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: StrategyEvolutionService = Depends(  # noqa: B008
        Provide[ApplicationContainer.strategy_evolution_service]
    ),
) -> dict[str, Any]:
    return await svc.get_recommendations(lookback_days=lookback_days)


# ── Phase 20.6 — Research Intelligence ───────────────────────────────────────

@router.get("/cohorts", summary="Trade cohort performance across all dimensions")
@inject
async def get_cohorts(
    lookback_days: int = Query(90, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeCohortService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_cohort_service]
    ),
) -> dict[str, Any]:
    return await svc.get_all_cohorts(lookback_days=lookback_days)


@router.get("/edges", summary="Multi-dimensional edge discovery across signal combinations")
@inject
async def get_edges(
    lookback_days: int = Query(90, ge=7, le=365),
    min_trades: int = Query(10, ge=5, le=100),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: EdgeDiscoveryService = Depends(  # noqa: B008
        Provide[ApplicationContainer.edge_discovery_service]
    ),
) -> dict[str, Any]:
    return await svc.discover_edges(lookback_days=lookback_days, min_trades=min_trades)


@router.get("/clusters/loss", summary="Loss co-occurrence clusters (failure patterns)")
@inject
async def get_loss_clusters(
    lookback_days: int = Query(90, ge=7, le=365),
    top_n: int = Query(15, ge=5, le=50),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: LossClusterService = Depends(  # noqa: B008
        Provide[ApplicationContainer.loss_cluster_service]
    ),
) -> dict[str, Any]:
    return await svc.get_loss_clusters(lookback_days=lookback_days, top_n=top_n)


@router.get("/clusters/winners", summary="Winner pattern clusters (recurring winning setups)")
@inject
async def get_winner_clusters(
    lookback_days: int = Query(90, ge=7, le=365),
    top_n: int = Query(15, ge=5, le=50),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: LossClusterService = Depends(  # noqa: B008
        Provide[ApplicationContainer.loss_cluster_service]
    ),
) -> dict[str, Any]:
    return await svc.get_winner_clusters(lookback_days=lookback_days, top_n=top_n)


@router.get("/replay/{signal_id}", summary="Lifecycle event timeline for a single signal")
@inject
async def get_replay_timeline(
    signal_id: str,
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeReplayService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_replay_service]
    ),
) -> dict[str, Any]:
    return await svc.get_timeline(signal_id=signal_id)


@router.post("/replay/backfill", summary="Trigger replay event backfill (admin)")
@inject
async def backfill_replay(
    limit: int = Query(300, ge=1, le=1000),
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    svc: TradeReplayService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_replay_service]
    ),
) -> dict[str, Any]:
    return await svc.backfill_unreplayed(limit=limit)


@router.get("/replay/coverage", summary="Replay event coverage statistics")
@inject
async def get_replay_coverage(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: TradeReplayService = Depends(  # noqa: B008
        Provide[ApplicationContainer.trade_replay_service]
    ),
) -> dict[str, Any]:
    return await svc.get_replay_coverage()


@router.get("/operator/status", summary="Live scanner status panel")
@inject
async def get_operator_status(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OperatorObservabilityService = Depends(  # noqa: B008
        Provide[ApplicationContainer.operator_observability_service]
    ),
) -> dict[str, Any]:
    return await svc.get_status_panel()


@router.get("/research/dashboard", summary="Aggregated research intelligence dashboard")
@inject
async def get_research_dashboard(
    lookback_days: int = Query(30, ge=1, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: ResearchDashboardService = Depends(  # noqa: B008
        Provide[ApplicationContainer.research_dashboard_service]
    ),
) -> dict[str, Any]:
    return await svc.get_full_dashboard(lookback_days=lookback_days)


@router.get("/research/risk", summary="Risk of ruin analytics (research view)")
@inject
async def get_research_risk(
    lookback_days: int = Query(90, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: ResearchDashboardService = Depends(  # noqa: B008
        Provide[ApplicationContainer.research_dashboard_service]
    ),
) -> dict[str, Any]:
    return await svc.get_risk_analytics(lookback_days=lookback_days)


@router.get("/intelligence/weekly", summary="Weekly intelligence report (14 sections)")
@inject
async def get_weekly_intelligence(
    lookback_days: int = Query(7, ge=1, le=30),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: WeeklyIntelligenceReportService = Depends(  # noqa: B008
        Provide[ApplicationContainer.weekly_intelligence_report_service]
    ),
) -> dict[str, Any]:
    return await svc.generate(lookback_days=lookback_days)


# ── Phase 21.2 — Overlay Effectiveness (§4-§8, §15) ──────────────────────────

@router.get(
    "/overlay/effectiveness/{overlay_name}",
    summary="§4 Named overlay effectiveness: fired vs baseline win-rate",
)
@inject
async def get_overlay_effectiveness(
    overlay_name: str,
    lookback_days: int = Query(30, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OverlayEffectivenessService = Depends(  # noqa: B008
        Provide[ApplicationContainer.overlay_effectiveness_service]
    ),
) -> dict[str, Any]:
    return await svc.get_overlay_effectiveness_report(
        overlay_name=overlay_name, lookback_days=lookback_days
    )


@router.get(
    "/overlay/events",
    summary="§5 Event overlay effectiveness: with-event vs no-event win-rate",
)
@inject
async def get_event_overlay_effectiveness(
    lookback_days: int = Query(60, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OverlayEffectivenessService = Depends(  # noqa: B008
        Provide[ApplicationContainer.overlay_effectiveness_service]
    ),
) -> dict[str, Any]:
    return await svc.get_event_effectiveness(lookback_days=lookback_days)


@router.get(
    "/overlay/regime-stability",
    summary="§6 Regime stability overlay: STABLE / TRANSITION / UNSTABLE breakdown",
)
@inject
async def get_regime_stability_effectiveness(
    lookback_days: int = Query(30, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OverlayEffectivenessService = Depends(  # noqa: B008
        Provide[ApplicationContainer.overlay_effectiveness_service]
    ),
) -> dict[str, Any]:
    return await svc.get_regime_stability_report(lookback_days=lookback_days)


@router.get(
    "/overlay/execution-quality",
    summary="§7 Execution grade A/B/C/D win-rate monotonicity check",
)
@inject
async def get_execution_quality_effectiveness(
    lookback_days: int = Query(30, ge=7, le=365),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OverlayEffectivenessService = Depends(  # noqa: B008
        Provide[ApplicationContainer.overlay_effectiveness_service]
    ),
) -> dict[str, Any]:
    return await svc.get_execution_quality_report(lookback_days=lookback_days)


@router.get(
    "/overlay/milestones",
    summary="§15 Validation milestones: auto-evaluate at 200 / 500 / 1000 completed trades",
)
@inject
async def get_overlay_milestones(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    svc: OverlayEffectivenessService = Depends(  # noqa: B008
        Provide[ApplicationContainer.overlay_effectiveness_service]
    ),
) -> dict[str, Any]:
    return await svc.check_validation_milestones()
