"""ResearchDashboardService — Phase 20.6 Sections 7, 8, 9, 11.

The unified research intelligence dashboard. Aggregates all Phase 20.6
analytics sub-services into a single callable interface.

Section 7  — Portfolio Correlation Analytics (effective exposure + heat)
Section 8  — Risk of Ruin Analytics (drawdown ladder, worst streak, RoR estimate)
Section 9  — Frontend Research Dashboard (top cohorts, symbols, regimes, clusters)
Section 11 — Recommendation Engine (evidence-based, read-only, never auto-changes)

Sub-service dependencies (all optional — falls back to inline SQL if not provided):
  cohort_svc           TradeCohortService
  edge_svc             EdgeDiscoveryService
  cluster_svc          LossClusterService
  observability_svc    OperatorObservabilityService
  portfolio_svc        PortfolioIntelligenceService (Phase 19)
  strategy_evo_svc     StrategyEvolutionService (Phase 20.5)

Usage (all optional, compose as needed):
  svc = ResearchDashboardService(
      session_factory,
      cohort_svc=cohort_svc,
      edge_svc=edge_svc,
      cluster_svc=cluster_svc,
      observability_svc=obs_svc,
      portfolio_svc=portfolio_svc,
      strategy_evo_svc=evo_svc,
  )
  dashboard = await svc.get_full_dashboard(lookback_days=30)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class ResearchDashboardService:
    """Aggregated research intelligence and recommendation hub."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cohort_svc=None,
        edge_svc=None,
        cluster_svc=None,
        observability_svc=None,
        portfolio_svc=None,
        strategy_evo_svc=None,
    ) -> None:
        self._sf          = session_factory
        self._cohort      = cohort_svc
        self._edge        = edge_svc
        self._cluster     = cluster_svc
        self._obs         = observability_svc
        self._portfolio   = portfolio_svc
        self._strategy    = strategy_evo_svc

    # ── Section 9 — Full Research Dashboard ───────────────────────────────────

    async def get_full_dashboard(self, lookback_days: int = 30) -> dict:
        """Return the complete research dashboard — all sections.

        Runs all sub-service calls concurrently. Each section is independently
        fault-tolerant; an error in one section does not fail the dashboard.
        """
        coros = {
            "top_cohorts":          self._get_cohorts(lookback_days),
            "edge_discovery":       self._get_edges(lookback_days),
            "loss_clusters":        self._get_loss_clusters(lookback_days),
            "winner_clusters":      self._get_winner_clusters(lookback_days),
            "best_symbols":         self._best_symbols(lookback_days),
            "worst_symbols":        self._worst_symbols(lookback_days),
            "regime_ranking":       self._regime_ranking(lookback_days),
            "time_window_ranking":  self._time_window_ranking(lookback_days),
            "correlation_analytics": self._correlation_analytics(lookback_days),
            "risk_of_ruin":         self._risk_of_ruin(lookback_days),
            "recommendations":      self._recommendations(lookback_days),
            "operator_status":      self._operator_status(),
        }

        results = await asyncio.gather(*coros.values(), return_exceptions=True)
        sections: dict = {}
        for key, result in zip(coros.keys(), results):
            sections[key] = (
                result if not isinstance(result, Exception)
                else {"error": str(result)}
            )

        rec_count  = len(sections.get("recommendations", {}).get("recommendations", []))
        edge_count = sections.get("edge_discovery", {}).get("edge_discovered_count", 0)

        return {
            "dashboard_type":          "RESEARCH_INTELLIGENCE",
            "lookback_days":           lookback_days,
            "edges_discovered":        edge_count,
            "recommendations_count":   rec_count,
            "sections":                sections,
            "generated_at":            datetime.now(UTC).isoformat(),
        }

    # ── Section 7 — Portfolio Correlation Analytics ───────────────────────────

    async def get_correlation_analytics(self, lookback_days: int = 30) -> dict:
        return await self._correlation_analytics(lookback_days)

    async def _correlation_analytics(self, lookback_days: int) -> dict:
        # Prefer Phase 19 PortfolioIntelligenceService if wired up
        if self._portfolio:
            try:
                corr = await self._portfolio.get_correlation_report(lookback_days)
                sect = await self._portfolio.get_sector_exposure()
                heat = await self._portfolio.get_portfolio_heat()
                return {
                    "correlation":      corr,
                    "sector_exposure":  sect,
                    "portfolio_heat":   heat,
                }
            except Exception as exc:
                _log.warning("research.correlation_svc_error: %s", exc)

        # Inline fallback: most-traded symbol pairs (simple co-occurrence)
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT ticker, sector,
                               COUNT(*) FILTER (WHERE was_accepted) AS active_n,
                               ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate
                        FROM signal_analytics
                        WHERE outcome IS NOT NULL AND created_at >= :cutoff
                        GROUP BY ticker, sector
                        ORDER BY active_n DESC
                        LIMIT 20
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                r_sect = await db.execute(
                    text("""
                        SELECT sector, COUNT(*) FILTER (WHERE was_accepted) AS n
                        FROM signal_analytics
                        WHERE outcome IS NULL AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY sector
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                sect_rows = r_sect.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        total_active = sum(int(r[2] or 0) for r in rows)
        symbols = [
            {
                "ticker":     row[0], "sector": row[1],
                "active_n":   int(row[2] or 0),
                "win_rate":   float(row[3]) if row[3] else None,
                "exposure_pct": round(int(row[2] or 0) / max(total_active, 1) * 100, 1),
            }
            for row in rows
        ]
        sectors = [
            {"sector": row[0], "active_n": int(row[1] or 0),
             "concentration_pct": round(int(row[1] or 0) / max(total_active, 1) * 100, 1)}
            for row in sect_rows
        ]
        top_sector = sectors[0] if sectors else {}
        return {
            "symbol_exposure":   symbols,
            "sector_exposure":   sectors,
            "top_sector_concentration_pct": top_sector.get("concentration_pct"),
            "alert": "SECTOR_CONCENTRATION" if top_sector.get("concentration_pct", 0) > 50 else None,
        }

    # ── Section 8 — Risk of Ruin Analytics ────────────────────────────────────

    async def get_risk_analytics(self, lookback_days: int = 90) -> dict:
        return await self._risk_of_ruin(lookback_days)

    async def _risk_of_ruin(self, lookback_days: int) -> dict:
        # Prefer Phase 19 PortfolioIntelligenceService if wired up
        if self._portfolio:
            try:
                ror = await self._portfolio.get_risk_of_ruin(lookback_days)
                # Extend with additional RoR metrics computed inline
                extra = await self._ror_extra(lookback_days)
                return {**ror, **extra}
            except Exception as exc:
                _log.warning("research.ror_svc_error: %s", exc)

        return await self._ror_extra(lookback_days)

    async def _ror_extra(self, lookback_days: int) -> dict:
        """Risk of ruin extra metrics: worst streak, avg streak, rough RoR estimate."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          DATE(created_at AT TIME ZONE 'UTC') AS d,
                          SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                          SUM(CASE WHEN stop_hit  THEN 1 ELSE 0 END)  AS losses,
                          ROUND(SUM(COALESCE(pnl_pct,current_return_pct,0))*100,4) AS daily_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY d ORDER BY d
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                r_all = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) FILTER (WHERE target_hit)  AS wins,
                          COUNT(*) FILTER (WHERE stop_hit)    AS losses,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl,
                          ROUND(STDDEV(COALESCE(pnl_pct,current_return_pct))*100,4) AS std_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                all_row = r_all.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        # Loss streak analysis
        cur_loss = max_loss = cur_win = max_win = 0
        loss_streaks: list[int] = []
        for row in rows:
            if int(row[2] or 0) > int(row[1] or 0):
                cur_loss += 1
                max_loss  = max(max_loss, cur_loss)
                cur_win   = 0
            elif int(row[1] or 0) > int(row[2] or 0):
                cur_win  += 1
                max_win   = max(max_win, cur_win)
                if cur_loss > 0:
                    loss_streaks.append(cur_loss)
                cur_loss  = 0
            else:
                cur_loss  = 0
                cur_win   = 0
        if cur_loss > 0:
            loss_streaks.append(cur_loss)

        avg_streak = sum(loss_streaks) / len(loss_streaks) if loss_streaks else 0

        # Cumulative drawdown
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for row in rows:
            cum  += float(row[3] or 0)
            peak  = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        # Rough Risk of Ruin estimate (Kelly-based approximation):
        # p = win_rate, q = 1-p, b = avg_win / avg_loss
        wins   = int(all_row[0] or 0)
        losses = int(all_row[1] or 0)
        n      = wins + losses
        wr     = wins / max(n, 1)
        lr     = 1 - wr
        # simplified RoR ≈ (lr/wr)^N for geometric sequence; capped at 1.0
        if wr > 0 and lr > 0:
            ror_est = min(1.0, (lr / wr) ** 10)  # over next 10 consecutive losses
        else:
            ror_est = None

        return {
            "lookback_days":          lookback_days,
            "trading_days_sampled":   len(rows),
            "worst_loss_streak_days": max_loss,
            "avg_loss_streak_days":   round(avg_streak, 1),
            "best_win_streak_days":   max_win,
            "current_drawdown_pct":   round(max(0.0, peak - cum), 4),
            "max_drawdown_pct":       round(max_dd, 4),
            "total_trades":           n,
            "overall_win_rate_pct":   round(wr * 100, 1),
            "avg_pnl_pct":            float(all_row[2]) if all_row[2] else None,
            "pnl_std_pct":            float(all_row[3]) if all_row[3] else None,
            "ror_estimate_10streak":  round(ror_est * 100, 2) if ror_est else None,
            "scaling_safe":           max_loss <= 3 and (ror_est or 0) < 0.10,
        }

    # ── Section 11 — Recommendation Engine ───────────────────────────────────

    async def get_recommendations(self, lookback_days: int = 30) -> dict:
        """Evidence-based recommendations. Read-only. Never auto-changes strategy."""
        return await self._recommendations(lookback_days)

    async def _recommendations(self, lookback_days: int) -> dict:
        recs: list[dict] = []

        # 1. From StrategyEvolutionService (Phase 20.5) if wired
        if self._strategy:
            try:
                evo = await self._strategy.get_recommendations(lookback_days)
                recs.extend(evo.get("recommendations", []))
            except Exception as exc:
                _log.warning("research.recommendations_evo_error: %s", exc)

        # 2. From cohort analysis (Phase 20.6)
        if self._cohort:
            try:
                cohort_result = await self._cohort.get_top_cohorts(lookback_days)
                recs += _cohort_recommendations(cohort_result)
            except Exception as exc:
                _log.warning("research.recommendations_cohort_error: %s", exc)

        # 3. From edge discovery (Phase 20.6)
        if self._edge:
            try:
                edges = await self._edge.discover_edges(lookback_days, min_trades=15)
                recs += _edge_recommendations(edges)
            except Exception as exc:
                _log.warning("research.recommendations_edge_error: %s", exc)

        # 4. Inline: symbol-level underperformers
        recs += await self._symbol_recommendations(lookback_days)

        # Sort by priority
        _pri = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        recs.sort(key=lambda r: _pri.get(r.get("priority", "LOW"), 3))

        return {
            "lookback_days":          lookback_days,
            "recommendation_count":   len(recs),
            "note":                   "Observations only. No change is automatic. "
                                      "All strategy changes require ChangeControlService evidence gate.",
            "recommendations":        recs,
            "evaluated_at":           datetime.now(UTC).isoformat(),
        }

    # ── Symbol analytics ──────────────────────────────────────────────────────

    async def _best_symbols(self, lookback_days: int) -> list[dict]:
        return await self._symbol_performance(lookback_days, best=True)

    async def _worst_symbols(self, lookback_days: int) -> list[dict]:
        return await self._symbol_performance(lookback_days, best=False)

    async def _symbol_performance(self, lookback_days: int, best: bool) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        order  = "profit_factor DESC NULLS LAST" if best else "profit_factor ASC NULLS LAST"
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text(f"""
                        SELECT
                          ticker, sector,
                          COUNT(*) AS n,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          ::numeric,3) AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS expectancy
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY ticker, sector
                        HAVING COUNT(*) >= 5
                        ORDER BY {order}
                        LIMIT 10
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return [{"error": str(exc)}]

        return [
            {
                "ticker":          row[0],
                "sector":          row[1],
                "count":           int(row[2] or 0),
                "win_rate_pct":    float(row[3]) if row[3] else None,
                "profit_factor":   float(row[4]) if row[4] else None,
                "expectancy_pct":  float(row[5]) if row[5] else None,
            }
            for row in rows
        ]

    async def _regime_ranking(self, lookback_days: int) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT regime,
                               COUNT(*) AS n,
                               ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate,
                               ROUND(
                                 SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                                 NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                               ::numeric,3) AS profit_factor,
                               ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS expectancy
                        FROM signal_analytics
                        WHERE was_accepted=true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime HAVING COUNT(*) >= 5
                        ORDER BY profit_factor DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return [{"error": str(exc)}]

        return [
            {"regime": row[0], "count": int(row[1] or 0), "win_rate_pct": float(row[2] or 0),
             "profit_factor": float(row[3]) if row[3] else None,
             "expectancy_pct": float(row[4]) if row[4] else None}
            for row in rows
        ]

    async def _time_window_ranking(self, lookback_days: int) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          CASE
                            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                                + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                                 BETWEEN 570 AND 629 THEN '09:30-10:30'
                            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                                + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                                 BETWEEN 630 AND 719 THEN '10:30-12:00'
                            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                                + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                                 BETWEEN 720 AND 809 THEN '12:00-13:30'
                            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                                + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                                 BETWEEN 810 AND 869 THEN '13:30-14:30'
                            ELSE '14:30+'
                          END AS window,
                          COUNT(*) AS n,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4)       AS expectancy
                        FROM signal_analytics
                        WHERE was_accepted=true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY window HAVING COUNT(*) >= 5
                        ORDER BY expectancy DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return [{"error": str(exc)}]

        return [
            {"window": row[0], "count": int(row[1] or 0),
             "win_rate_pct": float(row[2] or 0),
             "expectancy_pct": float(row[3]) if row[3] else None}
            for row in rows
        ]

    async def _symbol_recommendations(self, lookback_days: int) -> list[dict]:
        """Generate inline symbol-level recommendations."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        recs = []
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT ticker,
                               COUNT(*) AS n,
                               ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100,1) AS wr,
                               ROUND(
                                 SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                                 NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                               ::numeric,3) AS pf
                        FROM signal_analytics
                        WHERE was_accepted=true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY ticker HAVING COUNT(*) >= 20
                        ORDER BY pf ASC NULLS LAST
                        LIMIT 5
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception:
            return []

        for row in rows:
            pf = float(row[3]) if row[3] else None
            wr = float(row[2]) if row[2] else None
            n  = int(row[1] or 0)
            if pf is not None and pf < 0.90:
                recs.append({
                    "id":          f"SYMBOL_{row[0]}_UNDERPERFORM",
                    "priority":    "HIGH" if pf < 0.75 else "MEDIUM",
                    "category":    "UNIVERSE_REMOVAL",
                    "title":       f"{row[0]} consistently underperforming (PF {pf:.2f})",
                    "recommendation": (
                        f"{row[0]} has PF={pf:.2f}, WR={wr:.1f}% over {n} trades "
                        f"in {lookback_days}d. Consider reviewing symbol-specific conditions "
                        f"or temporarily removing from universe pending investigation."
                    ),
                    "supporting_evidence": f"n={n}, PF={pf:.2f}, WR={wr:.1f}%",
                    "expected_impact":     "Removing underperforming symbol improves portfolio PF.",
                    "min_trades_before_action": 50,
                    "change_category":     "UNIVERSE_REMOVAL",
                })
        return recs

    # ── Sub-service delegation (with fallbacks) ───────────────────────────────

    async def _get_cohorts(self, lookback_days: int) -> dict:
        if self._cohort:
            return await self._cohort.get_top_cohorts(lookback_days)
        return {"note": "TradeCohortService not wired up."}

    async def _get_edges(self, lookback_days: int) -> dict:
        if self._edge:
            return await self._edge.discover_edges(lookback_days, min_trades=15)
        return {"note": "EdgeDiscoveryService not wired up."}

    async def _get_loss_clusters(self, lookback_days: int) -> dict:
        if self._cluster:
            return await self._cluster.get_loss_clusters(lookback_days)
        return await self._inline_loss_clusters(lookback_days)

    async def _get_winner_clusters(self, lookback_days: int) -> dict:
        if self._cluster:
            return await self._cluster.get_winner_clusters(lookback_days)
        return {"note": "LossClusterService not wired up."}

    async def _operator_status(self) -> dict:
        if self._obs:
            return await self._obs.get_status_panel()
        return {"note": "OperatorObservabilityService not wired up."}

    async def _inline_loss_clusters(self, lookback_days: int) -> dict:
        """Minimal fallback when LossClusterService is not wired."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT COALESCE(failure_reason,'UNKNOWN') AS fr,
                               regime,
                               COUNT(*) AS n,
                               ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100,4) AS avg_pnl
                        FROM signal_analytics
                        WHERE stop_hit=true AND was_accepted=true AND created_at >= :cutoff
                        GROUP BY fr, regime HAVING COUNT(*) >= 3
                        ORDER BY n DESC LIMIT 10
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        return {
            "primary_clusters": [
                {"cluster": f"{row[0]} + {row[1]}", "failure_reason": row[0],
                 "regime": row[1], "frequency": int(row[2] or 0),
                 "avg_pnl_pct": float(row[3]) if row[3] else None}
                for row in rows
            ]
        }


# ── Recommendation generators from cohort/edge data ──────────────────────────

def _cohort_recommendations(cohort_result: dict) -> list[dict]:
    recs = []
    for cohort in cohort_result.get("bottom_cohorts", []):
        if cohort.get("count", 0) < 20:
            continue
        pf  = cohort.get("profit_factor")
        wr  = cohort.get("win_rate_pct")
        exp = cohort.get("expectancy_pct")
        if pf is None or pf >= 1.0:
            continue
        label = f"{cohort.get('cohort_type', '?')}={cohort.get('bucket', '?')}"
        recs.append({
            "id":          f"COHORT_{label.upper().replace(' ','')}",
            "priority":    "HIGH" if pf < 0.80 else "MEDIUM",
            "category":    "COMPONENT_PARAMETER",
            "title":       f"Cohort {label} has poor edge (PF {pf:.2f})",
            "recommendation": (
                f"Cohort '{label}' has PF={pf:.2f}, WR={wr:.1f}%, "
                f"expectancy={exp:.3f}% over {cohort.get('count')} trades. "
                f"This cohort is destroying capital. Investigate the combination "
                f"and consider filtering or restricting position sizing."
            ),
            "supporting_evidence": f"PF={pf:.2f}, WR={wr:.1f}%, n={cohort.get('count')}",
            "expected_impact":     "Restricting this cohort could materially improve PF.",
            "min_trades_before_action": 50,
            "change_category":     "COMPONENT_PARAMETER",
        })
    return recs[:3]  # cap at 3 cohort recommendations


def _edge_recommendations(edges: dict) -> list[dict]:
    recs = []
    for combo in edges.get("edge_discovered", [])[:3]:
        pf  = combo.get("profit_factor")
        wr  = combo.get("win_rate_pct")
        n   = combo.get("count", 0)
        lbl = combo.get("label", "?")
        if n < 15:
            continue
        recs.append({
            "id":          f"EDGE_{lbl.upper().replace(' ','').replace('|','')}",
            "priority":    "LOW",
            "category":    "COMPONENT_PARAMETER",
            "title":       f"Edge discovered: {lbl}",
            "recommendation": (
                f"Combination '{lbl}' shows PF={pf:.2f}, WR={wr:.1f}% over {n} trades. "
                f"This is a statistically meaningful edge. Consider prioritising these "
                f"setups for allocation when conditions align. Do not change scoring — "
                f"simply increase awareness of these conditions."
            ),
            "supporting_evidence": f"PF={pf:.2f}, WR={wr:.1f}%, n={n}",
            "expected_impact":     "Selective focus on discovered edges improves portfolio expectancy.",
            "min_trades_before_action": 30,
            "change_category":     "COMPONENT_PARAMETER",
        })
    return recs
