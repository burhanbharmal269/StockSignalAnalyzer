"""Signal Intelligence Router — analytics, leaderboard, and filter analytics.

GET  /api/v1/intelligence/signals/summary         — today's signal summary
GET  /api/v1/intelligence/signals/top-symbols     — top symbols by signal count
GET  /api/v1/intelligence/signals/sectors         — sector breakdown
GET  /api/v1/intelligence/strategies/leaderboard  — strategy performance leaderboard
GET  /api/v1/intelligence/filters                 — filter effectiveness report
POST /api/v1/intelligence/outcomes/check          — trigger outcome check cycle

Execution mode and lock state: use GET /api/v1/execution/status instead.
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from container import ApplicationContainer
from core.application.services.filter_analytics_service import FilterAnalyticsService
from core.application.services.optimization_insights_service import OptimizationInsightsService
from core.application.services.regime_performance_service import RegimePerformanceService
from core.application.services.signal_analytics_service import SignalAnalyticsService
from core.application.services.signal_leaderboard_service import SignalLeaderboardService
from core.application.services.signal_outcome_tracker_service import SignalOutcomeTrackerService
from core.application.services.strategy_performance_service import StrategyPerformanceService
from core.presentation.api.v1.dependencies.auth import require_no_force_change

router = APIRouter(prefix="/api/v1/intelligence", tags=["Signal Intelligence"])


@router.get("/signals/summary", summary="Today's signal summary")
@inject
async def get_signal_summary(
    analytics: SignalAnalyticsService = Depends(Provide[ApplicationContainer.signal_analytics_service]),
) -> dict:
    """Signal generation summary for today — always-on regardless of execution mode."""
    return await analytics.get_summary_today()


@router.get("/signals/top-symbols", summary="Top symbols by signal count")
@inject
async def get_top_symbols(
    limit: int = Query(10, ge=1, le=50),
    analytics: SignalAnalyticsService = Depends(Provide[ApplicationContainer.signal_analytics_service]),
) -> dict:
    symbols = await analytics.get_top_symbols_today(limit=limit)
    return {"top_symbols": symbols, "limit": limit}


@router.get("/signals/sectors", summary="Signal sector breakdown today")
@inject
async def get_sector_breakdown(
    analytics: SignalAnalyticsService = Depends(Provide[ApplicationContainer.signal_analytics_service]),
) -> dict:
    breakdown = await analytics.get_sector_breakdown_today()
    return {"sectors": breakdown}


@router.get("/strategies/leaderboard", summary="Strategy performance leaderboard")
@inject
async def get_strategy_leaderboard(
    lookback_days: int = Query(30, ge=1, le=365),
    performance_svc: StrategyPerformanceService = Depends(
        Provide[ApplicationContainer.strategy_performance_service]
    ),
) -> dict:
    """Strategy leaderboard ranked by expectancy. Requires outcome-tracked signal data."""
    leaderboard = await performance_svc.compute_leaderboard(lookback_days=lookback_days)
    return {
        "computed_at": leaderboard.computed_at.isoformat(),
        "lookback_days": leaderboard.lookback_days,
        "best_strategy": leaderboard.best_strategy.strategy_type if leaderboard.best_strategy else None,
        "worst_strategy": leaderboard.worst_strategy.strategy_type if leaderboard.worst_strategy else None,
        "strategies": [
            {
                "rank":                     m.rank,
                "strategy_type":            m.strategy_type,
                "signal_count":             m.signal_count,
                "accepted_count":           m.accepted_count,
                "win_rate":                 m.win_rate,
                "profit_factor":            m.profit_factor,
                "avg_return_pct":           m.avg_return_pct,
                "sharpe_ratio":             m.sharpe_ratio,
                "max_drawdown_pct":         m.max_drawdown_pct,
                "expectancy":               m.expectancy,
                "avg_holding_time_minutes": m.avg_holding_time_minutes,
                "avg_score":                m.avg_score,
                "avg_confidence":           m.avg_confidence,
                "component_scores": {
                    "trend":     m.avg_trend_score,
                    "volume":    m.avg_volume_score,
                    "vwap":      m.avg_vwap_score,
                    "oi":        m.avg_oi_score,
                    "sentiment": m.avg_sentiment_score,
                },
            }
            for m in leaderboard.strategies
        ],
    }


@router.get("/filters", summary="Filter effectiveness analysis")
@inject
async def get_filter_analytics(
    lookback_days: int = Query(30, ge=1, le=365),
    filter_svc: FilterAnalyticsService = Depends(
        Provide[ApplicationContainer.filter_analytics_service]
    ),
) -> dict:
    """Measures whether each filter improves or hurts signal quality."""
    report = await filter_svc.compute_report(lookback_days=lookback_days)
    return {
        "computed_at": report.computed_at.isoformat(),
        "lookback_days": report.lookback_days,
        "total_signals_evaluated": report.total_signals_evaluated,
        "total_signals_accepted": report.total_signals_accepted,
        "acceptance_rate": round(
            report.total_signals_accepted / max(report.total_signals_evaluated, 1) * 100, 1
        ),
        "improving_filters": [f.filter_name for f in report.improving_filters],
        "hurting_filters": [f.filter_name for f in report.hurting_filters],
        "filters": [
            {
                "filter_name":        f.filter_name,
                "description":        f.description,
                "signals_before":     f.signals_before,
                "signals_after":      f.signals_after,
                "pass_rate_pct":      f.pass_rate_pct,
                "rejected_count":     f.rejected_count,
                "win_rate_passed":    f.win_rate_passed,
                "win_rate_rejected":  f.win_rate_rejected,
                "performance_delta":  f.performance_delta,
                "verdict":            f.verdict,
            }
            for f in report.filters
        ],
    }


@router.post("/outcomes/check", summary="Trigger outcome check cycle (admin)")
@inject
async def trigger_outcome_check(
    _user=Depends(require_no_force_change),
    tracker: SignalOutcomeTrackerService = Depends(
        Provide[ApplicationContainer.signal_outcome_tracker_service]
    ),
) -> dict:
    """Manually trigger one outcome-check cycle for all pending accepted signals."""
    return await tracker.run_once()


@router.get("/regime-performance", summary="Strategy performance by market regime")
@inject
async def get_regime_performance(
    lookback_days: int = Query(30, ge=1, le=365),
    regime_svc: RegimePerformanceService = Depends(
        Provide[ApplicationContainer.regime_performance_service]
    ),
) -> dict:
    """Cross-tabulation of regime × strategy win rates. Shows which strategy works best per regime."""
    report = await regime_svc.compute_report(lookback_days=lookback_days)
    return {
        "computed_at": report.computed_at.isoformat(),
        "lookback_days": report.lookback_days,
        "best_per_regime": report.best_per_regime,
        "metrics": [
            {
                "regime":          m.regime,
                "strategy_type":   m.strategy_type,
                "signal_count":    m.signal_count,
                "win_count":       m.win_count,
                "loss_count":      m.loss_count,
                "partial_count":   m.partial_count,
                "win_rate":        m.win_rate,
                "profit_factor":   m.profit_factor,
                "avg_return_pct":  m.avg_return_pct,
                "expectancy":      m.expectancy,
            }
            for m in report.regime_metrics
        ],
    }


@router.get("/leaderboard", summary="Symbol, sector, and regime leaderboards")
@inject
async def get_leaderboard(
    lookback_days: int = Query(30, ge=1, le=365),
    leaderboard_svc: SignalLeaderboardService = Depends(
        Provide[ApplicationContainer.signal_leaderboard_service]
    ),
) -> dict:
    """Ranked leaderboards by win rate and expectancy for symbols, sectors, and regimes."""
    lb = await leaderboard_svc.compute_leaderboard(lookback_days=lookback_days)

    def _serialize(entries):
        return [
            {
                "rank":           e.rank,
                "name":           e.name,
                "signal_count":   e.signal_count,
                "win_count":      e.win_count,
                "win_rate":       e.win_rate,
                "profit_factor":  e.profit_factor,
                "avg_return_pct": e.avg_return_pct,
                "expectancy":     e.expectancy,
            }
            for e in entries
        ]

    return {
        "computed_at":   lb.computed_at.isoformat(),
        "lookback_days": lb.lookback_days,
        "symbols":       _serialize(lb.symbols),
        "sectors":       _serialize(lb.sectors),
        "regimes":       _serialize(lb.regimes),
    }


@router.get("/insights", summary="Automatic optimization insights")
@inject
async def get_optimization_insights(
    lookback_days: int = Query(30, ge=1, le=365),
    insights_svc: OptimizationInsightsService = Depends(
        Provide[ApplicationContainer.optimization_insights_service]
    ),
) -> dict:
    """Rule-based text recommendations derived from signal analytics data."""
    report = await insights_svc.compute_insights(lookback_days=lookback_days)
    return {
        "computed_at":   report.computed_at.isoformat(),
        "lookback_days": report.lookback_days,
        "insight_count": len(report.insights),
        "insights": [
            {
                "priority":     i.priority,
                "category":     i.category,
                "title":        i.title,
                "description":  i.description,
                "metric_value": i.metric_value,
                "metric_label": i.metric_label,
            }
            for i in report.insights
        ],
    }
