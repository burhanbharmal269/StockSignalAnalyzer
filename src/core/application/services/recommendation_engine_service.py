"""RecommendationEngineService — Phase 23 §8.

Generates evidence-driven research recommendations.  Every recommendation
includes trade count, z-statistic, confidence interval, expected improvement,
risk, and rollback plan.

Rules:
  - Minimum 30 completed trades in a cohort before analysing it.
  - z >= 1.96 (p < 0.05) → READY_FOR_REVIEW
  - z >= 1.65 (p < 0.10) → EMERGING
  - Otherwise            → WAIT

No automatic implementation.  Status never becomes APPROVED automatically;
that requires human action via the /research/recommendations/{id}/review API.

All recommendations are READ-ONLY observations — they cannot modify any
strategy parameter.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.application.services.cohort_engine_service import CohortEngineService

_log = logging.getLogger(__name__)

_MIN_COHORT_TRADES = 30
_Z_READY      = 1.96
_Z_EMERGING   = 1.65


def _two_prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-proportion z-test: cohort win rate vs baseline win rate."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p1 = k1 / n1
    p2 = k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    denom = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    return (p1 - p2) / denom if denom > 0 else 0.0


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, center - margin), min(1.0, center + margin)


class RecommendationEngineService:
    """Scans cohort performance data and generates statistically grounded recommendations."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cohort_engine: CohortEngineService,
    ) -> None:
        self._sf     = session_factory
        self._cohort = cohort_engine

    async def generate_recommendations(self) -> list[dict[str, Any]]:
        """Scan all dimensions and return recommendations sorted by z-statistic."""
        baseline = await self._get_baseline()
        if baseline["n"] < _MIN_COHORT_TRADES:
            return [{
                "id":                    None,
                "recommendation_type":   "INSUFFICIENT_DATA",
                "dimension":             "overall",
                "cohort_key":            None,
                "direction":             "WAIT",
                "trade_count":           baseline["n"],
                "z_statistic":           None,
                "p_value":               None,
                "ci_low":                None,
                "ci_high":               None,
                "cohort_win_rate":       baseline["win_rate"],
                "baseline_win_rate":     baseline["win_rate"],
                "cohort_pf":             baseline["pf"],
                "status":                "WAIT",
                "expected_improvement":  None,
                "risk_description":      None,
                "rollback_plan":         "N/A — no change proposed",
                "message": (
                    f"Only {baseline['n']} completed trades. "
                    f"Need ≥{_MIN_COHORT_TRADES} to analyse cohorts."
                ),
                "generated_at": datetime.now(UTC).isoformat(),
            }]

        recs: list[dict[str, Any]] = []
        for dimension in ["score_bucket", "regime", "instrument_type",
                          "time_window", "qualification_grade", "market_context"]:
            try:
                cohorts = await self._cohort.get_cohort_stats(dimension, min_trades=_MIN_COHORT_TRADES)
                for cohort in cohorts:
                    rec = self._analyse_cohort(cohort, baseline, dimension)
                    if rec:
                        recs.append(rec)
            except Exception as exc:
                _log.debug("recommendation.%s failed: %s", dimension, exc)

        # Deduplicate and sort by |z|
        recs.sort(key=lambda r: abs(r.get("z_statistic") or 0), reverse=True)
        return recs[:20]   # top 20 recommendations

    async def get_frozen_policy_response(self, proposed_change: str) -> dict[str, Any]:
        """Architecture freeze gate response for proposed strategy modifications."""
        baseline = await self._get_baseline()
        n        = baseline["n"]
        passes   = n >= 200

        return {
            "status":            "ALLOWED" if passes else "ARCHITECTURE_FROZEN",
            "completed_trades":  n,
            "minimum_required":  200,
            "proposed_change":   proposed_change,
            "message": (
                "✓ Sufficient trade history. Proceed with walk-forward validation."
                if passes else
                f"✗ ARCHITECTURE FROZEN. Only {n} completed trades. "
                f"Need ≥200 before any strategy modification."
            ),
            "requirements": {
                "minimum_trades":           200,
                "preferred_trades":         500,
                "statistical_significance": "p < 0.05 (z ≥ 1.96)",
                "walk_forward":             True,
                "rollback_plan":            True,
                "impact_analysis":          True,
            },
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _get_baseline(self) -> dict[str, Any]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS n,
                        ROUND(AVG(CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                        ROUND(
                            SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) /
                            NULLIF(ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)), 0),
                            3
                        ) AS pf
                    FROM signal_analytics
                    WHERE outcome IN ('WIN','LOSS','PARTIAL')
                      AND was_accepted = true
                      AND pnl_pct IS NOT NULL
                """))
                row = r.fetchone()
            return {
                "n":        int(row.n or 0),
                "win_rate": float(row.win_rate or 0) / 100,
                "pf":       float(row.pf or 1.0) if row.pf is not None else 1.0,
            }
        except Exception as exc:
            _log.warning("recommendation.baseline failed: %s", exc)
            return {"n": 0, "win_rate": 0.0, "pf": 1.0}

    def _analyse_cohort(
        self,
        cohort: dict[str, Any],
        baseline: dict[str, Any],
        dimension: str,
    ) -> dict[str, Any] | None:
        n1 = cohort["trade_count"]
        if n1 < _MIN_COHORT_TRADES:
            return None

        wr_cohort   = cohort["win_rate"] / 100
        wr_baseline = baseline["win_rate"]
        n_base      = baseline["n"]

        k1 = round(wr_cohort  * n1)
        k2 = round(wr_baseline * n_base)

        z = _two_prop_z(k1, n1, k2, n_base)
        p = _z_to_p(z)

        ci_low, ci_high = _wilson_ci(k1, n1)

        if abs(z) >= _Z_READY:
            status = "READY_FOR_REVIEW"
        elif abs(z) >= _Z_EMERGING:
            status = "EMERGING"
        else:
            status = "WAIT"

        direction = "OUTPERFORMING" if wr_cohort > wr_baseline else "UNDERPERFORMING"

        pf_delta = (
            (cohort["profit_factor"] or 1.0) - baseline["pf"]
            if cohort["profit_factor"] is not None else 0.0
        )

        return {
            "id":                    None,
            "recommendation_type":   f"COHORT_{direction}",
            "dimension":             dimension,
            "cohort_key":            cohort["cohort"],
            "direction":             direction,
            "trade_count":           n1,
            "z_statistic":           round(z, 3),
            "p_value":               round(p, 4),
            "ci_low":                round(ci_low * 100, 2),
            "ci_high":               round(ci_high * 100, 2),
            "cohort_win_rate":       round(wr_cohort * 100, 2),
            "baseline_win_rate":     round(wr_baseline * 100, 2),
            "cohort_pf":             cohort.get("profit_factor"),
            "status":                status,
            "expected_improvement":  (
                f"PF delta +{pf_delta:.3f} vs baseline {baseline['pf']:.3f}"
                if pf_delta > 0 else
                f"PF delta {pf_delta:.3f} vs baseline (underperforming)"
            ),
            "risk_description": (
                f"Cohort n={n1}, CI [{ci_low*100:.1f}%–{ci_high*100:.1f}%]. "
                f"Small sample risk." if n1 < 100 else
                f"Cohort n={n1}. Statistical confidence adequate."
            ),
            "rollback_plan": "No change proposed — observation only. "
                             "Review in research cube before any capital reallocation.",
            "generated_at": datetime.now(UTC).isoformat(),
        }


def _z_to_p(z: float) -> float:
    """One-tailed p-value from z-statistic (normal approximation)."""
    abs_z = abs(z)
    # Abramowitz & Stegun approximation
    t = 1.0 / (1.0 + 0.2316419 * abs_z)
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    p = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * abs_z ** 2) * poly
    return min(1.0, max(0.0, p * 2))   # two-tailed
