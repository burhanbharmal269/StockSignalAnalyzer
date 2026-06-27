"""WeeklyResearchService — Phase 23 §11.

Generates a comprehensive weekly research report by composing all Phase 22/23
services.  Reports are persisted to weekly_research_snapshots and returned as
structured JSON.

Reports can be retrieved as:
  JSON (this service)
  CSV  (via research_router — flattened from JSON)
  API  (research_router endpoints)
  Frontend (ResearchCommandCenter component)

Auto-generation: called by the background task registry every Friday at 15:45 IST.
On-demand: GET /api/v1/research/report/weekly
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from core.application.services.cohort_engine_service import CohortEngineService
    from core.application.services.deployment_readiness_service import DeploymentReadinessService
    from core.application.services.go_no_go_service import GoNoGoService
    from core.application.services.live_validation_service import LiveValidationService
    from core.application.services.overlay_effectiveness_service import OverlayEffectivenessService
    from core.application.services.recommendation_engine_service import RecommendationEngineService
    from core.application.services.statistical_validation_service import StatisticalValidationService
    from core.application.services.strategy_health_service import StrategyHealthService

_log = logging.getLogger(__name__)


class WeeklyResearchService:
    """Composes all research services into the weekly platform report."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        strategy_health_service: "StrategyHealthService",
        deployment_readiness_service: "DeploymentReadinessService",
        go_no_go_service: "GoNoGoService",
        cohort_engine_service: "CohortEngineService",
        recommendation_engine_service: "RecommendationEngineService",
        statistical_validation_service: "StatisticalValidationService",
        overlay_effectiveness_service: "OverlayEffectivenessService",
        live_validation_service: "LiveValidationService",
    ) -> None:
        self._sf            = session_factory
        self._health        = strategy_health_service
        self._readiness     = deployment_readiness_service
        self._go_no_go      = go_no_go_service
        self._cohorts       = cohort_engine_service
        self._recs          = recommendation_engine_service
        self._stat_val      = statistical_validation_service
        self._overlay_eff   = overlay_effectiveness_service
        self._live_val      = live_validation_service

    async def generate_weekly_report(self) -> dict[str, Any]:
        """Build and persist the full weekly research report."""
        today     = datetime.now(UTC).date()
        # Week: Monday → Friday
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)
        week_end   = week_start + timedelta(days=4)

        report = await self._build_report(week_start, week_end)

        # Persist
        try:
            async with self._sf() as db:
                await db.execute(text("""
                    INSERT INTO weekly_research_snapshots (week_start, week_end, report_json)
                    VALUES (:ws, :we, :rj)
                    ON CONFLICT DO NOTHING
                """), {
                    "ws": week_start,
                    "we": week_end,
                    "rj": json.dumps(report),
                })
                await db.commit()
        except Exception as exc:
            _log.warning("weekly_research.persist_failed: %s", exc)

        return report

    async def get_latest_report(self) -> dict[str, Any] | None:
        """Return the most recently stored report (or generate one if none exists)."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT report_json, created_at
                    FROM weekly_research_snapshots
                    ORDER BY week_start DESC
                    LIMIT 1
                """))
                row = r.fetchone()
        except Exception as exc:
            _log.warning("weekly_research.get_latest failed: %s", exc)
            return None

        if not row:
            return None

        try:
            report = json.loads(row.report_json)
            report["_retrieved_at"] = datetime.now(UTC).isoformat()
            return report
        except Exception:
            return None

    async def get_all_reports(self, limit: int = 12) -> list[dict[str, Any]]:
        """Return summaries of the last N weekly reports."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT week_start, week_end, created_at,
                           (report_json::jsonb->>'platform_health')::jsonb->>'overall' AS overall_health
                    FROM weekly_research_snapshots
                    ORDER BY week_start DESC
                    LIMIT :lim
                """), {"lim": limit})
                rows = r.fetchall()
        except Exception:
            return []

        return [
            {
                "week_start": str(row.week_start),
                "week_end":   str(row.week_end),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "overall_health": float(row.overall_health) if row.overall_health else None,
            }
            for row in rows
        ]

    # ── Private ───────────────────────────────────────────────────────────────

    async def _build_report(self, week_start: date, week_end: date) -> dict[str, Any]:
        report: dict[str, Any] = {
            "week_start": str(week_start),
            "week_end":   str(week_end),
            "generated_at": datetime.now(UTC).isoformat(),
        }

        # Platform Health
        try:
            report["platform_health"] = await self._health.get_health_score()
        except Exception as exc:
            _log.warning("weekly.platform_health failed: %s", exc)
            report["platform_health"] = {"error": str(exc)}

        # Deployment Readiness
        try:
            rd = await self._readiness.get_readiness()
            readiness_score = rd.get("overall_score", 0)
            gng = await self._go_no_go.evaluate(readiness_score)
            report["deployment_readiness"] = rd
            report["go_no_go"] = gng
        except Exception as exc:
            _log.warning("weekly.deployment failed: %s", exc)
            report["deployment_readiness"] = {"error": str(exc)}
            report["go_no_go"] = {"error": str(exc)}

        # Cohort Rankings
        try:
            report["cohort_rankings"] = {
                "best_regimes":      await self._cohort_top_bottom("regime"),
                "best_time_windows": await self._cohort_top_bottom("time_window"),
                "best_instruments":  await self._cohort_top_bottom("instrument_type"),
                "best_qual_grades":  await self._cohort_top_bottom("qualification_grade"),
                "score_buckets":     await self._cohort_top_bottom("score_bucket"),
                "market_contexts":   await self._cohort_top_bottom("market_context"),
                "day_of_week":       await self._cohort_top_bottom("day_of_week"),
                "dte_buckets":       await self._cohort_top_bottom("dte_bucket"),
            }
        except Exception as exc:
            _log.warning("weekly.cohorts failed: %s", exc)
            report["cohort_rankings"] = {"error": str(exc)}

        # Statistical Validation
        try:
            report["statistical_validation"] = {
                "milestones":   await self._stat_val.get_milestone_gates(),
                "confidence":   await self._stat_val.get_confidence_intervals(),
            }
        except Exception as exc:
            _log.warning("weekly.stat_val failed: %s", exc)
            report["statistical_validation"] = {"error": str(exc)}

        # Overlay Effectiveness
        try:
            report["overlay_effectiveness"] = await self._overlay_eff.get_overlay_effectiveness()
        except Exception as exc:
            _log.warning("weekly.overlay_eff failed: %s", exc)
            report["overlay_effectiveness"] = {"error": str(exc)}

        # Recommendations
        try:
            report["recommendations"] = await self._recs.generate_recommendations()
        except Exception as exc:
            _log.warning("weekly.recommendations failed: %s", exc)
            report["recommendations"] = []

        # Live vs Paper
        try:
            report["live_vs_paper"] = await self._live_val.get_comparison()
        except Exception as exc:
            _log.warning("weekly.live_val failed: %s", exc)
            report["live_vs_paper"] = {"error": str(exc)}

        # Signals summary (this week)
        try:
            report["signals_summary"] = await self._signals_week_summary(week_start)
        except Exception as exc:
            _log.warning("weekly.signals_summary failed: %s", exc)
            report["signals_summary"] = {}

        return report

    async def _cohort_top_bottom(self, dimension: str, n: int = 3) -> dict[str, Any]:
        rows = await self._cohorts.get_cohort_stats(dimension, min_trades=5)
        return {
            "top":    rows[:n],
            "bottom": list(reversed(rows[-n:])) if len(rows) >= n else [],
            "total_cohorts_with_data": len(rows),
        }

    async def _signals_week_summary(self, week_start: date) -> dict[str, Any]:
        week_start_dt = datetime.combine(week_start, datetime.min.time()).replace(tzinfo=UTC)
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*)                                                    AS total,
                    SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END)              AS accepted,
                    SUM(CASE WHEN NOT was_accepted THEN 1 ELSE 0 END)          AS rejected,
                    SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)             AS wins,
                    SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END)            AS losses,
                    ROUND(AVG(CASE WHEN was_accepted THEN adjusted_score END)::numeric, 1) AS avg_score,
                    ROUND(AVG(CASE WHEN was_accepted THEN confidence END)::numeric, 1)     AS avg_conf,
                    COUNT(DISTINCT ticker)                                      AS unique_symbols
                FROM signal_analytics
                WHERE created_at >= :ws
            """), {"ws": week_start_dt})
            row = r.fetchone()

        if not row:
            return {}
        return {
            "total": int(row.total or 0),
            "accepted": int(row.accepted or 0),
            "rejected": int(row.rejected or 0),
            "wins": int(row.wins or 0),
            "losses": int(row.losses or 0),
            "avg_score": float(row.avg_score or 0),
            "avg_confidence": float(row.avg_conf or 0),
            "unique_symbols": int(row.unique_symbols or 0),
        }
