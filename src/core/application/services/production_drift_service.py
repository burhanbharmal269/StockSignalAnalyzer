"""ProductionDriftService — Phase 22 §9.

Compares a reference period against a comparison period and detects
statistically significant changes using a two-proportion z-test for
win rate and a Welch-like z-test for continuous metrics.

Default: reference = 30-day window ending 7 days ago; comparison = last 7 days.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Minimum samples to run a z-test
_MIN_N = 20


def _two_prop_z(k1: int, n1: int, k2: int, n2: int) -> tuple[float, str]:
    """Two-proportion z-test (H0: p1 == p2). Returns (z_stat, significance)."""
    if n1 < _MIN_N or n2 < _MIN_N:
        return (0.0, "INSUFFICIENT_DATA")
    p1 = k1 / n1
    p2 = k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    denom = math.sqrt(max(1e-12, p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)))
    z = (p2 - p1) / denom
    sig = "SIGNIFICANT" if abs(z) >= 1.96 else "NOT_SIGNIFICANT"
    return (round(z, 4), sig)


def _continuous_z(mean1: float, std1: float, n1: int, mean2: float, std2: float, n2: int) -> tuple[float, str]:
    """Welch z-test for two sample means. Returns (z_stat, significance)."""
    if n1 < _MIN_N or n2 < _MIN_N:
        return (0.0, "INSUFFICIENT_DATA")
    se = math.sqrt(max(1e-12, std1 ** 2 / n1 + std2 ** 2 / n2))
    z = (mean2 - mean1) / se
    sig = "SIGNIFICANT" if abs(z) >= 1.96 else "NOT_SIGNIFICANT"
    return (round(z, 4), sig)


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old == 0.0:
        return None
    return round((new - old) / abs(old) * 100, 2)


class ProductionDriftService:
    """Detects statistical drift between two time periods."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_drift_report(
        self,
        *,
        ref_days:  int = 30,   # reference window length (ends at ref_end)
        cmp_days:  int = 7,    # comparison window length (most recent)
        gap_days:  int = 0,    # gap between comparison end and reference start
    ) -> dict[str, Any]:
        """Compare reference vs comparison periods across key pipeline metrics."""
        now     = datetime.now(UTC)
        cmp_end = now
        cmp_start = cmp_end - timedelta(days=cmp_days)
        ref_end   = cmp_start - timedelta(days=gap_days)
        ref_start = ref_end - timedelta(days=ref_days)

        periods = {
            "reference":   {"start": ref_start.isoformat(), "end": ref_end.isoformat(),   "days": ref_days},
            "comparison":  {"start": cmp_start.isoformat(), "end": cmp_end.isoformat(),   "days": cmp_days},
        }

        metrics_ref = await self._fetch_period_metrics(ref_start, ref_end)
        metrics_cmp = await self._fetch_period_metrics(cmp_start, cmp_end)

        drift_checks = self._compute_drift(metrics_ref, metrics_cmp)
        drifted_n = sum(1 for d in drift_checks if d["significance"] == "SIGNIFICANT")

        return {
            "periods":       periods,
            "reference":     metrics_ref,
            "comparison":    metrics_cmp,
            "drift_checks":  drift_checks,
            "summary": {
                "total_checks":         len(drift_checks),
                "significant_drifts":   drifted_n,
                "system_stable":        drifted_n == 0,
            },
            "evaluated_at": now.isoformat(),
        }

    # ── Data fetch ────────────────────────────────────────────────────────────

    async def _fetch_period_metrics(
        self, start: datetime, end: datetime
    ) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) AS total_signals,
                    SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted,
                    SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN target_hit THEN 1 ELSE 0 END) AS wins,
                    ROUND(AVG(COALESCE(confidence, 0))::numeric, 4) AS avg_confidence,
                    ROUND(STDDEV_POP(COALESCE(confidence, 0))::numeric, 4) AS std_confidence,
                    ROUND(AVG(COALESCE(adjusted_score, 0))::numeric, 4) AS avg_score,
                    ROUND(STDDEV_POP(COALESCE(adjusted_score, 0))::numeric, 4) AS std_score,
                    ROUND(AVG(CASE WHEN was_accepted THEN COALESCE(data_quality_score, 0) ELSE NULL END)::numeric, 4) AS avg_dq,
                    ROUND(STDDEV_POP(CASE WHEN was_accepted THEN COALESCE(data_quality_score, 0) ELSE NULL END)::numeric, 4) AS std_dq,
                    ROUND(AVG(CASE WHEN outcome IS NOT NULL THEN COALESCE(pnl_pct, 0) ELSE NULL END)::numeric, 6) AS avg_pnl,
                    ROUND(STDDEV_POP(CASE WHEN outcome IS NOT NULL THEN COALESCE(pnl_pct, 0) ELSE NULL END)::numeric, 6) AS std_pnl
                FROM signal_analytics
                WHERE created_at >= :start AND created_at < :end
            """), {"start": start, "end": end})
            row = r.fetchone()

            r2 = await db.execute(text("""
                SELECT execution_grade, COUNT(*) AS n
                FROM signal_analytics
                WHERE created_at >= :start AND created_at < :end
                  AND execution_grade IS NOT NULL
                GROUP BY execution_grade
            """), {"start": start, "end": end})
            grade_rows = r2.fetchall()

        total    = int(row[0] or 0)
        accepted = int(row[1] or 0)
        completed = int(row[2] or 0)
        wins     = int(row[3] or 0)

        grade_dist: dict[str, int] = {g[0]: int(g[1]) for g in grade_rows if g[0]}
        graded_total = sum(grade_dist.values())
        ab_rate = (
            (grade_dist.get("A", 0) + grade_dist.get("B", 0)) / graded_total * 100
            if graded_total > 0 else None
        )

        return {
            "total_signals":   total,
            "accepted":        accepted,
            "completed":       completed,
            "wins":            wins,
            "acceptance_rate": round(accepted / total * 100, 2) if total > 0 else None,
            "win_rate":        round(wins / completed * 100, 2) if completed > 0 else None,
            "avg_confidence":  float(row[4] or 0),
            "std_confidence":  float(row[5] or 0),
            "avg_score":       float(row[6] or 0),
            "std_score":       float(row[7] or 0),
            "avg_dq":          float(row[8] or 0) if row[8] else None,
            "std_dq":          float(row[9] or 0) if row[9] else None,
            "avg_pnl":         float(row[10]) if row[10] else None,
            "std_pnl":         float(row[11]) if row[11] else None,
            "ab_grade_rate":   round(ab_rate, 2) if ab_rate is not None else None,
            "grade_distribution": grade_dist,
        }

    # ── Drift computation ─────────────────────────────────────────────────────

    def _compute_drift(
        self,
        ref: dict[str, Any],
        cmp: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        # 1. Win rate (two-proportion z-test)
        z, sig = _two_prop_z(ref["wins"], ref["completed"], cmp["wins"], cmp["completed"])
        results.append({
            "metric":         "win_rate",
            "reference":      ref["win_rate"],
            "comparison":     cmp["win_rate"],
            "pct_change":     _pct_change(ref["win_rate"], cmp["win_rate"]),
            "z_stat":         z,
            "significance":   sig,
            "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
        })

        # 2. Acceptance rate (two-proportion z-test)
        z, sig = _two_prop_z(ref["accepted"], ref["total_signals"], cmp["accepted"], cmp["total_signals"])
        results.append({
            "metric":         "acceptance_rate",
            "reference":      ref["acceptance_rate"],
            "comparison":     cmp["acceptance_rate"],
            "pct_change":     _pct_change(ref["acceptance_rate"], cmp["acceptance_rate"]),
            "z_stat":         z,
            "significance":   sig,
            "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
        })

        # 3. Avg confidence (continuous z-test)
        z, sig = _continuous_z(
            ref["avg_confidence"], ref["std_confidence"], ref["total_signals"],
            cmp["avg_confidence"], cmp["std_confidence"], cmp["total_signals"],
        )
        results.append({
            "metric":         "avg_confidence",
            "reference":      ref["avg_confidence"],
            "comparison":     cmp["avg_confidence"],
            "pct_change":     _pct_change(ref["avg_confidence"], cmp["avg_confidence"]),
            "z_stat":         z,
            "significance":   sig,
            "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
        })

        # 4. Avg score (continuous z-test)
        z, sig = _continuous_z(
            ref["avg_score"], ref["std_score"], ref["total_signals"],
            cmp["avg_score"], cmp["std_score"], cmp["total_signals"],
        )
        results.append({
            "metric":         "avg_score",
            "reference":      ref["avg_score"],
            "comparison":     cmp["avg_score"],
            "pct_change":     _pct_change(ref["avg_score"], cmp["avg_score"]),
            "z_stat":         z,
            "significance":   sig,
            "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
        })

        # 5. A/B grade rate (two-proportion z-test using graded totals)
        ref_ab = ref["grade_distribution"].get("A", 0) + ref["grade_distribution"].get("B", 0)
        cmp_ab = cmp["grade_distribution"].get("A", 0) + cmp["grade_distribution"].get("B", 0)
        ref_graded = sum(ref["grade_distribution"].values())
        cmp_graded = sum(cmp["grade_distribution"].values())
        z, sig = _two_prop_z(ref_ab, ref_graded, cmp_ab, cmp_graded)
        results.append({
            "metric":         "ab_grade_rate",
            "reference":      ref["ab_grade_rate"],
            "comparison":     cmp["ab_grade_rate"],
            "pct_change":     _pct_change(ref["ab_grade_rate"], cmp["ab_grade_rate"]),
            "z_stat":         z,
            "significance":   sig,
            "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
        })

        # 6. Avg PnL per trade (continuous, only if data exists)
        if ref["avg_pnl"] is not None and cmp["avg_pnl"] is not None and ref["std_pnl"] and cmp["std_pnl"]:
            z, sig = _continuous_z(
                ref["avg_pnl"], ref["std_pnl"], ref["completed"],
                cmp["avg_pnl"], cmp["std_pnl"], cmp["completed"],
            )
            results.append({
                "metric":         "avg_pnl_pct",
                "reference":      round(ref["avg_pnl"] * 100, 4) if ref["avg_pnl"] else None,
                "comparison":     round(cmp["avg_pnl"] * 100, 4) if cmp["avg_pnl"] else None,
                "pct_change":     _pct_change(ref["avg_pnl"], cmp["avg_pnl"]),
                "z_stat":         z,
                "significance":   sig,
                "direction":      "IMPROVED" if z > 0 else ("DEGRADED" if z < 0 else "UNCHANGED"),
            })

        return results
