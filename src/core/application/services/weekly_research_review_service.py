"""WeeklyResearchReviewService — Phase 25 Section 7.

Generates the automated weekly research review every Friday (or on demand).
Aggregates across all Phase 24/25 analytics tables. No manual SQL needed.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.platform_constants import (
    ARCHITECTURE_STATUS,
    STRATEGY_VERSION,
    CONFIDENCE_VERSION,
    OVERLAY_VERSION,
    RISK_VERSION,
    TARGET_VERSION,
)

_log = logging.getLogger(__name__)


class WeeklyResearchReviewService:
    """Produces the weekly research report from live analytics data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def generate(self, lookback_days: int = 7) -> dict:
        """Generate the full weekly review for the past `lookback_days`."""
        now = datetime.now(UTC)

        sections = await _gather(
            self._architecture_status(),
            self._experiment_status(),
            self._signal_performance(lookback_days),
            self._target_calibration(lookback_days),
            self._best_worst_cohorts(lookback_days),
            self._overlay_effectiveness(lookback_days),
            self._component_ranking(lookback_days),
            self._premium_efficiency(lookback_days),
            self._portfolio_health(),
            self._operations_health(),
        )

        (arch, experiments, performance, calibration,
         cohorts, overlays, components, premium,
         portfolio, ops) = sections

        return {
            "generated_at":          now.isoformat(),
            "lookback_days":         lookback_days,
            "week_ending":           date.today().isoformat(),

            "section_1_architecture": arch,
            "section_2_experiments":  experiments,
            "section_3_performance":  performance,
            "section_4_calibration":  calibration,
            "section_5_cohorts":      cohorts,
            "section_6_overlays":     overlays,
            "section_7_components":   components,
            "section_8_premium":      premium,
            "section_9_portfolio":    portfolio,
            "section_10_operations":  ops,
            "recommendation_summary": self._recommendations(performance, calibration, experiments),
        }

    async def _architecture_status(self) -> dict:
        return {
            "architecture_status":  ARCHITECTURE_STATUS,
            "strategy_version":     STRATEGY_VERSION,
            "confidence_version":   CONFIDENCE_VERSION,
            "overlay_version":      OVERLAY_VERSION,
            "risk_version":         RISK_VERSION,
            "target_version":       TARGET_VERSION,
            "frozen_since":         "2026-06-30",
        }

    async def _experiment_status(self) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'DRAFT')     AS draft,
                    COUNT(*) FILTER (WHERE status = 'ACTIVE')    AS active,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed,
                    COUNT(*) FILTER (WHERE status = 'REJECTED')  AS rejected,
                    COUNT(*)                                      AS total
                FROM experiments
            """))
            row = dict(r.fetchone()._mapping) if r.rowcount != 0 else {}

            r2 = await db.execute(text("""
                SELECT experiment_id, title, status, treatment_allocation_pct,
                       approval_status, created_at
                FROM experiments WHERE status = 'ACTIVE'
                ORDER BY started_at DESC LIMIT 5
            """))
            active = [dict(x._mapping) for x in r2.fetchall()]

        return {
            "counts":          row,
            "active_experiments": active,
        }

    async def _signal_performance(self, days: int) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*)                                          AS total_accepted,
                    COUNT(*) FILTER (WHERE outcome = 'WIN')          AS wins,
                    COUNT(*) FILTER (WHERE outcome = 'LOSS')         AS losses,
                    COUNT(*) FILTER (WHERE outcome = 'EXPIRED')      AS expired,
                    COUNT(*) FILTER (WHERE outcome IS NULL OR outcome = 'OPEN') AS open_signals,
                    ROUND(AVG(pnl_pct)::numeric, 4)                  AS avg_pnl,
                    ROUND(AVG(mfe_pct)::numeric, 4)                  AS avg_mfe,
                    ROUND(AVG(mae_pct)::numeric, 4)                  AS avg_mae,
                    ROUND(SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN pnl_pct < 0 THEN ABS(pnl_pct) ELSE 0 END), 0)::numeric, 3) AS profit_factor,
                    ROUND(AVG(adjusted_score)::numeric, 2)           AS avg_score,
                    ROUND(AVG(confidence)::numeric, 2)               AS avg_confidence
                FROM signal_analytics
                WHERE was_accepted = true
                  AND created_at >= NOW() - (:days || ' days')::interval
            """), {"days": days})
            perf = dict(r.fetchone()._mapping)

        total = int(perf.get("wins") or 0) + int(perf.get("losses") or 0) + int(perf.get("expired") or 0)
        perf["win_rate"]  = round(int(perf.get("wins") or 0)   / total * 100, 1) if total else None
        perf["loss_rate"] = round(int(perf.get("losses") or 0) / total * 100, 1) if total else None
        perf["expired_rate"] = round(int(perf.get("expired") or 0) / total * 100, 1) if total else None
        return perf

    async def _target_calibration(self, days: int) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    ROUND(AVG(configured_target_pct)::numeric, 2)    AS avg_configured_target,
                    ROUND(AVG(recommended_target_pct)::numeric, 2)   AS avg_recommended_target,
                    ROUND(AVG(mfe_pct)::numeric, 2)                  AS avg_mfe,
                    ROUND(AVG(target_realism_pct)::numeric, 1)       AS avg_target_realism,
                    ROUND(AVG(target_confidence)::numeric, 1)        AS avg_target_confidence,
                    COUNT(*) FILTER (WHERE target_realism_pct < 50)  AS unrealistic_count,
                    COUNT(*) FILTER (WHERE target_realism_pct >= 70) AS realistic_count,
                    COUNT(*) FILTER (WHERE mfe_pct IS NOT NULL)      AS with_mfe
                FROM signal_analytics
                WHERE was_accepted = true
                  AND created_at >= NOW() - (:days || ' days')::interval
            """), {"days": days})
            cal = dict(r.fetchone()._mapping)

        with_mfe = int(cal.get("with_mfe") or 0)
        cal["unrealistic_rate"] = round(int(cal.get("unrealistic_count") or 0) / with_mfe * 100, 1) if with_mfe else None
        cal["calibration_status"] = (
            "WELL_CALIBRATED"    if (cal.get("avg_target_realism") or 0) >= 70
            else "SLIGHTLY_AGGRESSIVE" if (cal.get("avg_target_realism") or 0) >= 45
            else "AGGRESSIVE"
        )
        return cal

    async def _best_worst_cohorts(self, days: int) -> dict:
        sql = """
            SELECT
                :group_field AS group_label,
                COUNT(*) AS n,
                ROUND(AVG(mfe_pct)::numeric, 2) AS avg_mfe,
                COUNT(*) FILTER (WHERE target_hit) AS wins,
                ROUND(AVG(adjusted_score)::numeric, 2) AS avg_score
            FROM signal_analytics
            WHERE was_accepted = true
              AND created_at >= NOW() - (:days || ' days')::interval
              AND mfe_pct IS NOT NULL
            GROUP BY 1
            HAVING COUNT(*) >= 3
            ORDER BY avg_mfe DESC
        """
        async with self._sf() as db:
            r_regime = await db.execute(text("""
                SELECT COALESCE(regime,'UNKNOWN') AS group_label, COUNT(*) AS n,
                       ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe,
                       COUNT(*) FILTER (WHERE target_hit) AS wins,
                       ROUND(AVG(adjusted_score)::numeric,2) AS avg_score
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND mfe_pct IS NOT NULL
                GROUP BY 1 HAVING COUNT(*)>=3 ORDER BY avg_mfe DESC
            """), {"days": days})
            by_regime = [dict(x._mapping) for x in r_regime.fetchall()]

            r_sym = await db.execute(text("""
                SELECT ticker AS group_label, COUNT(*) AS n,
                       ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe,
                       COUNT(*) FILTER (WHERE target_hit) AS wins,
                       ROUND(AVG(adjusted_score)::numeric,2) AS avg_score
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND mfe_pct IS NOT NULL
                GROUP BY 1 HAVING COUNT(*)>=2 ORDER BY avg_mfe DESC
            """), {"days": days})
            by_symbol = [dict(x._mapping) for x in r_sym.fetchall()]

        return {
            "by_regime": {"best": by_regime[:3], "worst": by_regime[-3:][::-1]},
            "by_symbol": {"best": by_symbol[:5], "worst": by_symbol[-5:][::-1]},
        }

    async def _overlay_effectiveness(self, days: int) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COALESCE(market_context,'UNKNOWN') AS market_context,
                    COUNT(*) AS n,
                    ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe,
                    COUNT(*) FILTER (WHERE target_hit) AS wins,
                    ROUND(AVG(context_size_multiplier)::numeric,3) AS avg_size_mult
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND mfe_pct IS NOT NULL
                GROUP BY 1 ORDER BY avg_mfe DESC
            """), {"days": days})
            by_context = [dict(x._mapping) for x in r.fetchall()]

            r2 = await db.execute(text("""
                SELECT execution_grade, COUNT(*) AS n,
                       ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND execution_grade IS NOT NULL AND mfe_pct IS NOT NULL
                GROUP BY 1 ORDER BY execution_grade
            """), {"days": days})
            by_grade = [dict(x._mapping) for x in r2.fetchall()]

        return {"by_market_context": by_context, "by_execution_grade": by_grade}

    async def _component_ranking(self, days: int) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    CASE
                      WHEN trend_score >= 70 THEN 'HIGH_TREND'
                      WHEN trend_score >= 40 THEN 'MID_TREND'
                      ELSE 'LOW_TREND'
                    END AS trend_bucket,
                    COUNT(*) AS n,
                    ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND trend_score IS NOT NULL AND mfe_pct IS NOT NULL
                GROUP BY 1 ORDER BY avg_mfe DESC
            """), {"days": days})
            trend_rank = [dict(x._mapping) for x in r.fetchall()]

            r2 = await db.execute(text("""
                SELECT ROUND(mtf_score_bonus,1) AS mtf_bonus,
                       COUNT(*) AS n,
                       ROUND(AVG(mfe_pct)::numeric,2) AS avg_mfe
                FROM signal_analytics
                WHERE was_accepted=true AND created_at >= NOW() - (:days||' days')::interval
                  AND mtf_score_bonus IS NOT NULL AND mfe_pct IS NOT NULL
                GROUP BY 1 ORDER BY mtf_bonus DESC LIMIT 5
            """), {"days": days})
            mtf_rank = [dict(x._mapping) for x in r2.fetchall()]

        return {"trend_buckets": trend_rank, "mtf_bonus_buckets": mtf_rank}

    async def _premium_efficiency(self, days: int) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    ROUND(AVG(option_efficiency_score)::numeric,3) AS avg_efficiency,
                    ROUND(AVG(delta_efficiency)::numeric,3)        AS avg_delta_eff,
                    ROUND(AVG(time_in_profit_minutes)::numeric,0)  AS avg_time_in_profit,
                    ROUND(AVG(time_in_loss_minutes)::numeric,0)    AS avg_time_in_loss,
                    COUNT(*) FILTER (WHERE expiry_reason IS NOT NULL) AS classified_expired,
                    COUNT(*) FILTER (WHERE expiry_reason = 'WRONG_STRIKE_SELECTION') AS wrong_strike,
                    COUNT(*) FILTER (WHERE expiry_reason = 'UNREALISTIC_TARGET')     AS unrealistic_target,
                    COUNT(*) FILTER (WHERE expiry_reason = 'MISSED_BY_SMALL_MARGIN') AS near_miss
                FROM signal_analytics
                WHERE was_accepted=true
                  AND created_at >= NOW() - (:days||' days')::interval
            """), {"days": days})
            eff = dict(r.fetchone()._mapping)
        return eff

    async def _portfolio_health(self) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE state IN ('RISK_APPROVED','RISK_PENDING')) AS open_signals,
                    COUNT(*) FILTER (WHERE state = 'EXPIRED' AND created_at::date = CURRENT_DATE) AS expired_today,
                    COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS signals_today
                FROM signals
            """))
            row = dict(r.fetchone()._mapping) if r.rowcount != 0 else {}
        return row

    async def _operations_health(self) -> dict:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE severity IN ('CRITICAL','HIGH') AND end_time IS NULL) AS open_critical,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - '7 days'::interval) AS incidents_7d,
                    COUNT(*) FILTER (WHERE created_at >= NOW() - '1 day'::interval)  AS incidents_24h
                FROM incidents
            """))
            row = dict(r.fetchone()._mapping) if r.rowcount != 0 else {}
        return row

    @staticmethod
    def _recommendations(performance: dict, calibration: dict, experiments: dict) -> list[str]:
        recs: list[str] = []

        win_rate = performance.get("win_rate")
        if win_rate is not None and win_rate < 40:
            recs.append(f"Win rate {win_rate}% is below 40% — investigate signal quality and regime context")

        pf = performance.get("profit_factor")
        if pf is not None and float(pf) < 1.0:
            recs.append(f"Profit factor {pf} < 1.0 — losses exceeding gains; review SL levels")

        cal_status = calibration.get("calibration_status")
        if cal_status == "AGGRESSIVE":
            recs.append("Targets are overly aggressive — consider running EXP-calibration experiment")
        elif cal_status == "SLIGHTLY_AGGRESSIVE":
            recs.append("Targets slightly aggressive — monitor target realism; create experiment if persistent")

        active_count = len(experiments.get("active_experiments") or [])
        if active_count == 0:
            recs.append("No active experiments — platform is in pure observation mode")
        elif active_count > 3:
            recs.append(f"{active_count} active experiments may dilute statistical power; consider focusing on ≤2")

        if not recs:
            recs.append("Platform operating normally — continue evidence collection")

        return recs


async def _gather(*coros):
    """Run coroutines sequentially (avoid asyncio.gather import complexity)."""
    results = []
    for coro in coros:
        try:
            results.append(await coro)
        except Exception as exc:
            _log.warning("weekly_review.section_failed: %s", exc)
            results.append({"error": str(exc)})
    return results
