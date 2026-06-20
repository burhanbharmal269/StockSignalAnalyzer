"""WeeklyIntelligenceReportService — Phase 20.5 Section 26.

Generates a comprehensive weekly post-trade intelligence report covering:
  1.  Top Failure Reasons (most common causes of losses)
  2.  Top Success Reasons (dominant drivers of wins)
  3.  Model Failure Rate (ACCEPTABLE_LOSS vs MODEL_FAILURE vs EXECUTION_FAILURE)
  4.  Execution Failure Rate (from execution_lifecycle slippage data)
  5.  Premium Decay Analysis (DTE × IV patterns)
  6.  Recovery Analysis (how often stopped trades recover)
  7.  Best / Worst Components (by discriminative power)
  8.  Best / Worst Regimes (by PF)
  9.  Best / Worst Time Windows (IST hour buckets)
  10. MFE / MAE Summary (excursion profile)
  11. Stop Recovery Rate
  12. Signal Quality Distribution
  13. Gate Effectiveness Report
  14. Strategy Evolution Recommendations

All sections run concurrently via asyncio.gather.
Each section is independently fault-tolerant — an error in one section
does not fail the whole report.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")


class WeeklyIntelligenceReportService:
    """Comprehensive weekly post-trade intelligence report."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        strategy_evolution_svc=None,
        component_attribution_svc=None,
        trade_journey_svc=None,
    ) -> None:
        self._sf       = session_factory
        self._strategy = strategy_evolution_svc
        self._comp     = component_attribution_svc
        self._journey  = trade_journey_svc

    async def generate(self, lookback_days: int = 7) -> dict:
        """Generate all 14 sections of the weekly intelligence report concurrently."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        results = await asyncio.gather(
            self._s1_failure_reasons(cutoff),
            self._s2_success_reasons(cutoff),
            self._s3_model_failure_rate(cutoff),
            self._s4_execution_failure_rate(cutoff),
            self._s5_premium_decay(cutoff),
            self._s6_recovery_analysis(cutoff),
            self._s7_component_ranking(cutoff),
            self._s8_regime_ranking(cutoff),
            self._s9_time_window_ranking(cutoff),
            self._s10_mfe_mae_summary(cutoff),
            self._s11_quality_distribution(cutoff),
            self._s12_alerts(cutoff),
            return_exceptions=True,
        )

        labels = [
            "top_failure_reasons", "top_success_reasons", "model_failure_rate",
            "execution_failure_rate", "premium_decay_analysis", "recovery_analysis",
            "component_ranking", "regime_ranking", "time_window_ranking",
            "mfe_mae_summary", "signal_quality_distribution", "alerts",
        ]

        sections: dict = {}
        for label, result in zip(labels, results):
            sections[label] = (
                result if not isinstance(result, Exception)
                else {"error": str(result)}
            )

        # Optional sub-service sections
        if self._strategy:
            try:
                sections["strategy_evolution"] = await self._strategy.get_recommendations(lookback_days)
            except Exception as exc:
                sections["strategy_evolution"] = {"error": str(exc)}

        if self._comp:
            try:
                sections["gate_effectiveness"] = await self._comp.get_gate_effectiveness(lookback_days)
            except Exception as exc:
                sections["gate_effectiveness"] = {"error": str(exc)}

        # Summary header
        total_alerts = len(sections.get("alerts", {}).get("items", []))
        critical     = sum(1 for a in sections.get("alerts", {}).get("items", [])
                          if a.get("severity") == "CRITICAL")

        return {
            "report_type":     "WEEKLY_INTELLIGENCE",
            "lookback_days":   lookback_days,
            "period_start":    cutoff.isoformat(),
            "period_end":      datetime.now(UTC).isoformat(),
            "total_alerts":    total_alerts,
            "critical_alerts": critical,
            "sections":        sections,
            "generated_at":    datetime.now(UTC).isoformat(),
        }

    # ── Section 1 — Top Failure Reasons ──────────────────────────────────────

    async def _s1_failure_reasons(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          failure_reason,
                          COUNT(*) AS n,
                          ROUND(AVG(failure_confidence), 3) AS avg_conf,
                          ROUND(AVG(adjusted_score), 1)     AS avg_score,
                          ROUND(AVG(mfe_pct)*100, 3)        AS avg_mfe
                        FROM signal_analytics
                        WHERE stop_hit = true AND failure_reason IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY failure_reason
                        ORDER BY n DESC
                        LIMIT 10
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE stop_hit = true AND was_accepted = true AND created_at >= :cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])
        except Exception as exc:
            return {"error": str(exc)}

        return {
            "total_losses": total,
            "reasons": [
                {
                    "reason":          row[0],
                    "count":           int(row[1] or 0),
                    "pct_of_losses":   round(int(row[1] or 0) / total * 100, 1) if total else 0,
                    "avg_confidence":  float(row[2]) if row[2] else None,
                    "avg_score":       float(row[3]) if row[3] else None,
                    "avg_mfe_pct":     float(row[4]) if row[4] else None,
                }
                for row in rows
            ],
        }

    # ── Section 2 — Top Success Reasons ──────────────────────────────────────

    async def _s2_success_reasons(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          success_reason,
                          COUNT(*) AS n,
                          ROUND(AVG(success_confidence), 3)    AS avg_conf,
                          ROUND(AVG(time_to_target_minutes), 1) AS avg_time_to_target,
                          ROUND(AVG(adjusted_score), 1)         AS avg_score
                        FROM signal_analytics
                        WHERE target_hit = true AND success_reason IS NOT NULL
                          AND was_accepted = true
                          AND created_at >= :cutoff
                        GROUP BY success_reason
                        ORDER BY n DESC
                        LIMIT 10
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE target_hit = true AND was_accepted = true AND created_at >= :cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])
        except Exception as exc:
            return {"error": str(exc)}

        return {
            "total_wins": total,
            "reasons": [
                {
                    "reason":              row[0],
                    "count":               int(row[1] or 0),
                    "pct_of_wins":         round(int(row[1] or 0) / total * 100, 1) if total else 0,
                    "avg_confidence":      float(row[2]) if row[2] else None,
                    "avg_time_to_target":  float(row[3]) if row[3] else None,
                    "avg_score":           float(row[4]) if row[4] else None,
                }
                for row in rows
            ],
        }

    # ── Section 3 — Model Failure Rate ───────────────────────────────────────

    async def _s3_model_failure_rate(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          model_failure_class,
                          COUNT(*) AS n,
                          ROUND(AVG(signal_quality_score), 1) AS avg_quality
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND model_failure_class IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY model_failure_class
                        ORDER BY n DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()

                r_total = await db.execute(
                    text("SELECT COUNT(*) FROM signal_analytics WHERE was_accepted = true AND outcome IS NOT NULL AND created_at >= :cutoff"),
                    {"cutoff": cutoff},
                )
                total = int((r_total.fetchone() or [0])[0])
        except Exception as exc:
            return {"error": str(exc)}

        class_data = {row[0]: {"count": int(row[1] or 0), "avg_quality": float(row[2] or 0)} for row in rows}
        model_fail_n = class_data.get("MODEL_FAILURE", {}).get("count", 0)
        exec_fail_n  = class_data.get("EXECUTION_FAILURE", {}).get("count", 0)
        anomaly_n    = class_data.get("MARKET_ANOMALY", {}).get("count", 0)
        accept_n     = class_data.get("ACCEPTABLE_LOSS", {}).get("count", 0)

        attributed = sum(d["count"] for d in class_data.values())

        return {
            "total_completed":           total,
            "attributed_count":          attributed,
            "model_failure_count":       model_fail_n,
            "model_failure_rate_pct":    round(model_fail_n / max(attributed, 1) * 100, 1),
            "execution_failure_count":   exec_fail_n,
            "execution_failure_rate_pct": round(exec_fail_n / max(attributed, 1) * 100, 1),
            "market_anomaly_count":      anomaly_n,
            "market_anomaly_rate_pct":   round(anomaly_n / max(attributed, 1) * 100, 1),
            "acceptable_loss_count":     accept_n,
            "acceptable_loss_rate_pct":  round(accept_n / max(attributed, 1) * 100, 1),
            "breakdown":                 [
                {"class": k, "count": v["count"], "avg_quality": v["avg_quality"]}
                for k, v in class_data.items()
            ],
            "model_health": (
                "GOOD"     if model_fail_n / max(attributed, 1) < 0.20 else
                "ELEVATED" if model_fail_n / max(attributed, 1) < 0.35 else
                "POOR"
            ),
        }

    # ── Section 4 — Execution Failure Rate ───────────────────────────────────

    async def _s4_execution_failure_rate(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*)                                                                AS total,
                          ROUND(AVG(total_slippage_pct)::numeric, 4)                            AS avg_slippage,
                          ROUND(AVG(signal_to_fill_ms)::numeric, 0)                             AS avg_fill_ms,
                          COUNT(*) FILTER (WHERE total_slippage_pct > 1.5)                      AS high_slippage_n,
                          COUNT(*) FILTER (WHERE signal_to_fill_ms > 300000)                    AS slow_fill_n,
                          ROUND(percentile_cont(0.95) WITHIN GROUP
                                (ORDER BY total_slippage_pct)::numeric, 4)                      AS p95_slippage,
                          ROUND(percentile_cont(0.95) WITHIN GROUP
                                (ORDER BY signal_to_fill_ms)::numeric, 0)                       AS p95_fill_ms
                        FROM execution_lifecycle
                        WHERE created_at >= :cutoff
                          AND total_slippage_pct IS NOT NULL
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        if not row or not row[0]:
            return {"available": False, "note": "No execution_lifecycle data in period."}

        total = int(row[0] or 0)
        return {
            "total_executions":     total,
            "avg_slippage_pct":     float(row[1]) if row[1] else None,
            "avg_fill_ms":          float(row[2]) if row[2] else None,
            "high_slippage_count":  int(row[3] or 0),
            "high_slippage_pct":    round(int(row[3] or 0) / max(total, 1) * 100, 1),
            "slow_fill_count":      int(row[4] or 0),
            "slow_fill_pct":        round(int(row[4] or 0) / max(total, 1) * 100, 1),
            "p95_slippage_pct":     float(row[5]) if row[5] else None,
            "p95_fill_ms":          float(row[6]) if row[6] else None,
            "execution_health": (
                "GOOD"     if float(row[1] or 0) < 0.5 else
                "ELEVATED" if float(row[1] or 0) < 1.5 else
                "POOR"
            ),
        }

    # ── Section 5 — Premium Decay Analysis ───────────────────────────────────

    async def _s5_premium_decay(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) FILTER (WHERE premium_efficiency IS NOT NULL)  AS attributed_n,
                          ROUND(AVG(premium_efficiency), 4)                       AS avg_efficiency,
                          ROUND(AVG(premium_capture_ratio), 4)                    AS avg_capture,
                          ROUND(AVG(theta_drag_estimate), 4)                      AS avg_theta_drag,
                          ROUND(AVG(iv_drag_estimate), 4)                         AS avg_iv_drag,

                          -- DTE breakdown
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100
                                FILTER (WHERE dte <= 2), 4)                       AS low_dte_pnl,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100
                                FILTER (WHERE dte > 2), 4)                        AS norm_dte_pnl,
                          COUNT(*) FILTER (WHERE dte <= 2 AND stop_hit)           AS low_dte_losses,
                          COUNT(*) FILTER (WHERE dte > 2  AND stop_hit)           AS norm_dte_losses
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        def _f(v): return float(v) if v is not None else None

        return {
            "attributed_count":    int(row[0] or 0),
            "avg_premium_efficiency":   _f(row[1]),
            "avg_premium_capture_ratio": _f(row[2]),
            "avg_theta_drag_estimate":  _f(row[3]),
            "avg_iv_drag_estimate":     _f(row[4]),
            "low_dte_avg_pnl_pct":      _f(row[5]),
            "normal_dte_avg_pnl_pct":   _f(row[6]),
            "low_dte_loss_count":       int(row[7] or 0),
            "normal_dte_loss_count":    int(row[8] or 0),
            "premium_health": (
                "GOOD"     if row[1] and float(row[1]) > 0.70 else
                "MODERATE" if row[1] and float(row[1]) > 0.40 else
                "POOR"     if row[1] else
                "UNKNOWN"
            ),
        }

    # ── Section 6 — Recovery Analysis ────────────────────────────────────────

    async def _s6_recovery_analysis(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) FILTER (WHERE stop_hit)                          AS total_stops,
                          COUNT(*) FILTER (WHERE stop_hit AND mfe_pct > 0.005)      AS had_positive_mfe,
                          COUNT(*) FILTER (WHERE stop_hit AND mfe_pct > 0.25)       AS would_hit_25pct,
                          COUNT(*) FILTER (WHERE stop_hit AND mfe_pct > 0.50)       AS would_hit_50pct,
                          ROUND(AVG(mfe_pct)*100 FILTER (WHERE stop_hit), 3)        AS avg_mfe_on_losses,
                          COUNT(*) FILTER (WHERE stop_hit AND recovered_after_stop) AS actual_recovered
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        total    = int(row[0] or 0)
        pos_mfe  = int(row[1] or 0)
        hit_25   = int(row[2] or 0)
        hit_50   = int(row[3] or 0)
        actual_r = int(row[5] or 0)
        pct = lambda n: round(n / max(total, 1) * 100, 1)

        return {
            "total_stopouts":          total,
            "had_positive_mfe_count":  pos_mfe,
            "had_positive_mfe_pct":    pct(pos_mfe),
            "would_hit_breakeven_pct": pct(pos_mfe),
            "would_hit_25pct_target_pct": pct(hit_25),
            "would_hit_50pct_target_pct": pct(hit_50),
            "avg_mfe_on_losses_pct":   float(row[4]) if row[4] else None,
            "actual_recovered_count":  actual_r,
            "actual_recovered_pct":    pct(actual_r),
            "stop_too_tight_signal": (
                "HIGH"     if pos_mfe / max(total, 1) > 0.65 else
                "MODERATE" if pos_mfe / max(total, 1) > 0.45 else
                "LOW"
            ),
        }

    # ── Section 7 — Component Ranking ────────────────────────────────────────

    async def _s7_component_ranking(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ROUND(AVG(trend_score)        FILTER (WHERE target_hit), 2)  AS t_win,
                          ROUND(AVG(trend_score)        FILTER (WHERE stop_hit), 2)    AS t_loss,
                          ROUND(AVG(vwap_score)         FILTER (WHERE target_hit), 2)  AS vw_win,
                          ROUND(AVG(vwap_score)         FILTER (WHERE stop_hit), 2)    AS vw_loss,
                          ROUND(AVG(volume_score)       FILTER (WHERE target_hit), 2)  AS v_win,
                          ROUND(AVG(volume_score)       FILTER (WHERE stop_hit), 2)    AS v_loss,
                          ROUND(AVG(option_chain_score) FILTER (WHERE target_hit), 2)  AS oc_win,
                          ROUND(AVG(option_chain_score) FILTER (WHERE stop_hit), 2)    AS oc_loss,
                          ROUND(AVG(oi_score)           FILTER (WHERE target_hit), 2)  AS oi_win,
                          ROUND(AVG(oi_score)           FILTER (WHERE stop_hit), 2)    AS oi_loss,
                          ROUND(AVG(iv_score)           FILTER (WHERE target_hit), 2)  AS iv_win,
                          ROUND(AVG(iv_score)           FILTER (WHERE stop_hit), 2)    AS iv_loss
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        def _f(v): return float(v) if v is not None else None
        def _diff(w, l): return round(float(w or 0) - float(l or 0), 3) if w and l else None

        components = [
            {"name": "Trend",        "winner_avg": _f(row[0]),  "loser_avg": _f(row[1]),  "win_loss_delta": _diff(row[0], row[1])},
            {"name": "VWAP",         "winner_avg": _f(row[2]),  "loser_avg": _f(row[3]),  "win_loss_delta": _diff(row[2], row[3])},
            {"name": "Volume",       "winner_avg": _f(row[4]),  "loser_avg": _f(row[5]),  "win_loss_delta": _diff(row[4], row[5])},
            {"name": "Option Chain", "winner_avg": _f(row[6]),  "loser_avg": _f(row[7]),  "win_loss_delta": _diff(row[6], row[7])},
            {"name": "OI Buildup",   "winner_avg": _f(row[8]),  "loser_avg": _f(row[9]),  "win_loss_delta": _diff(row[8], row[9])},
            {"name": "IV",           "winner_avg": _f(row[10]), "loser_avg": _f(row[11]), "win_loss_delta": _diff(row[10], row[11])},
        ]
        components.sort(key=lambda c: -(c["win_loss_delta"] or 0))

        return {
            "best_components":  [c for c in components if (c["win_loss_delta"] or 0) > 0.5],
            "worst_components": [c for c in components if (c["win_loss_delta"] or 0) <= 0],
            "all_components":   components,
        }

    # ── Section 8 — Regime Ranking ────────────────────────────────────────────

    async def _s8_regime_ranking(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          regime,
                          COUNT(*) AS n,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END),0)
                          , 3) AS profit_factor
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime
                        HAVING COUNT(*) >= 5
                        ORDER BY profit_factor DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        all_r = [
            {
                "regime":        row[0],
                "count":         int(row[1] or 0),
                "win_rate_pct":  float(row[2]) if row[2] else None,
                "profit_factor": float(row[3]) if row[3] else None,
            }
            for row in rows
        ]
        return {
            "best_regimes":  all_r[:3],
            "worst_regimes": all_r[-3:][::-1] if len(all_r) > 3 else [],
            "all_regimes":   all_r,
        }

    # ── Section 9 — Time Window Ranking ──────────────────────────────────────

    async def _s9_time_window_ranking(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Kolkata'))::int AS ist_hour,
                          COUNT(*) AS n,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1)  AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100, 4)         AS avg_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY ist_hour
                        HAVING COUNT(*) >= 3
                        ORDER BY avg_pnl DESC NULLS LAST
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        all_t = [
            {
                "ist_hour":      int(row[0] or 9),
                "window":        f"{int(row[0] or 9):02d}:00–{int(row[0] or 9)+1:02d}:00 IST",
                "count":         int(row[1] or 0),
                "win_rate_pct":  float(row[2]) if row[2] else None,
                "avg_pnl_pct":   float(row[3]) if row[3] else None,
            }
            for row in rows
        ]
        return {
            "best_windows":  all_t[:3],
            "worst_windows": all_t[-3:][::-1] if len(all_t) > 3 else [],
            "all_windows":   all_t,
        }

    # ── Section 10 — MFE/MAE Summary ─────────────────────────────────────────

    async def _s10_mfe_mae_summary(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          ROUND(AVG(mfe_pct)*100, 3)                                  AS avg_mfe,
                          ROUND(AVG(mae_pct)*100, 3)                                  AS avg_mae,
                          ROUND(AVG(mfe_pct)*100 FILTER (WHERE target_hit), 3)        AS win_avg_mfe,
                          ROUND(AVG(mae_pct)*100 FILTER (WHERE target_hit), 3)        AS win_avg_mae,
                          ROUND(AVG(mfe_pct)*100 FILTER (WHERE stop_hit), 3)          AS loss_avg_mfe,
                          ROUND(AVG(mae_pct)*100 FILTER (WHERE stop_hit), 3)          AS loss_avg_mae,
                          ROUND(AVG(time_to_target_minutes) FILTER (WHERE target_hit), 1) AS avg_ttt,
                          ROUND(AVG(time_to_stop_minutes)   FILTER (WHERE stop_hit), 1)   AS avg_tts
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        def _f(v): return float(v) if v is not None else None

        return {
            "overall_avg_mfe_pct":     _f(row[0]),
            "overall_avg_mae_pct":     _f(row[1]),
            "winner_avg_mfe_pct":      _f(row[2]),
            "winner_avg_mae_pct":      _f(row[3]),
            "loser_avg_mfe_pct":       _f(row[4]),
            "loser_avg_mae_pct":       _f(row[5]),
            "avg_time_to_target_min":  _f(row[6]),
            "avg_time_to_stop_min":    _f(row[7]),
        }

    # ── Section 11 — Signal Quality Distribution ──────────────────────────────

    async def _s11_quality_distribution(self, cutoff: datetime) -> dict:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          signal_quality_category,
                          COUNT(*) AS n,
                          ROUND(AVG(signal_quality_score), 1) AS avg_score,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1) AS win_rate
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND signal_quality_category IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY signal_quality_category
                        ORDER BY avg_score DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        return {
            "distribution": [
                {
                    "category":      row[0],
                    "count":         int(row[1] or 0),
                    "avg_score":     float(row[2]) if row[2] else None,
                    "win_rate_pct":  float(row[3]) if row[3] else None,
                }
                for row in rows
            ]
        }

    # ── Section 12 — Alert Extraction ────────────────────────────────────────

    async def _s12_alerts(self, cutoff: datetime) -> dict:
        """Generate actionable alerts from the week's data."""
        alerts = []
        try:
            async with self._sf() as db:
                # Model failure rate alert
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) FILTER (WHERE model_failure_class = 'MODEL_FAILURE') AS mf,
                          COUNT(*) FILTER (WHERE model_failure_class IS NOT NULL)       AS total
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row = r.fetchone()
                mf_n = int(row[0] or 0)
                mf_total = int(row[1] or 1)
                if mf_n / mf_total > 0.35:
                    alerts.append({
                        "id": "HIGH_MODEL_FAILURE_RATE",
                        "severity": "CRITICAL",
                        "message": f"Model failure rate {mf_n/mf_total:.0%} — more than 35% of losses are poor-quality signals.",
                        "action": "Review score gate thresholds and component weights via ChangeControlService.",
                    })

                # Consecutive loss days
                r_daily = await db.execute(
                    text("""
                        SELECT DATE(created_at AT TIME ZONE 'UTC') AS d,
                               SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                               SUM(CASE WHEN stop_hit  THEN 1 ELSE 0 END)  AS losses
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY d ORDER BY d
                    """),
                    {"cutoff": cutoff},
                )
                days = r_daily.fetchall()
                consec = max_consec = 0
                for d in days:
                    if int(d[2] or 0) > int(d[1] or 0):
                        consec += 1
                        max_consec = max(max_consec, consec)
                    else:
                        consec = 0
                if max_consec >= 3:
                    alerts.append({
                        "id": "HIGH_CONSECUTIVE_LOSSES",
                        "severity": "HIGH" if max_consec >= 5 else "MEDIUM",
                        "message": f"{max_consec} consecutive loss days in period.",
                        "action": "Review regime and market context during loss streak.",
                    })

                # IMMEDIATE stop concentration
                r_imm = await db.execute(
                    text("""
                        SELECT COUNT(*) FILTER (WHERE COALESCE(time_to_stop_minutes,99) <= 15) AS imm,
                               COUNT(*) AS total
                        FROM signal_analytics
                        WHERE stop_hit = true AND was_accepted = true AND created_at >= :cutoff
                    """),
                    {"cutoff": cutoff},
                )
                row_imm = r_imm.fetchone()
                imm_n = int(row_imm[0] or 0)
                imm_total = int(row_imm[1] or 1)
                if imm_total >= 10 and imm_n / imm_total > 0.40:
                    alerts.append({
                        "id": "HIGH_IMMEDIATE_STOP_RATE",
                        "severity": "HIGH",
                        "message": f"{imm_n/imm_total:.0%} of stops hit within 15 minutes — entry quality or stop tightness issue.",
                        "action": "Review stop_timing_bucket distribution via TradeJourneyService.",
                    })

        except Exception as exc:
            return {"error": str(exc), "items": []}

        return {"items": alerts, "count": len(alerts)}
