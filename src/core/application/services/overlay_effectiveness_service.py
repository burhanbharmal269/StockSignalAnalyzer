"""OverlayEffectivenessService — Phase 21.2 §4-§8, §15.

Queries the signal_analytics table to measure whether each overlay is actually
adding value.  All methods are read-only analytics — no writes, no state.

Sections:
  §4  Overlay confidence attribution analysis (get_overlay_effectiveness_report)
  §5  Event overlay effectiveness (get_event_effectiveness)
  §6  Regime stability overlay effectiveness (get_regime_stability_report)
  §7  Execution quality grade → win-rate correlation (get_execution_quality_report)
  §8  Correlation overlay effectiveness (get_correlation_effectiveness_report)
  §15 Automated validation milestones at 200/500/1000 completed trades
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_MILESTONE_THRESHOLDS = (200, 500, 1000)


class OverlayEffectivenessService:
    """Read-only analytics for overlay pipeline effectiveness."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── §4 Generic Overlay Attribution ────────────────────────────────────────

    async def get_overlay_effectiveness_report(
        self,
        overlay_name: str,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """Measure whether a named overlay improves signal quality.

        Groups completed signals by whether the overlay fired (applied),
        comparing win-rate and average pnl_pct per group.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          CASE WHEN confidence_attribution_json::text LIKE :pat THEN 'fired' ELSE 'baseline' END AS grp,
                          COUNT(*) AS cnt,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct, 0))*100, 4)   AS avg_pnl,
                          ROUND(AVG(confidence), 2) AS avg_conf
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY grp
                        ORDER BY grp
                    """),
                    {"pat": f'%"name": "{overlay_name}"%applied": true%', "cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("overlay_effectiveness.query_failed overlay=%s: %s", overlay_name, exc)
            return {"error": str(exc), "overlay_name": overlay_name}

        groups: dict[str, dict] = {}
        for row in rows:
            groups[row[0]] = {
                "count":    int(row[1]),
                "win_rate": float(row[2] or 0),
                "avg_pnl":  float(row[3] or 0),
                "avg_conf": float(row[4] or 0),
            }

        fired    = groups.get("fired",    {"count": 0, "win_rate": 0, "avg_pnl": 0})
        baseline = groups.get("baseline", {"count": 0, "win_rate": 0, "avg_pnl": 0})

        wr_delta = fired["win_rate"] - baseline["win_rate"]
        pnl_delta = fired["avg_pnl"] - baseline["avg_pnl"]

        verdict = (
            "HELPING"   if wr_delta >= 2.0 or pnl_delta >= 0.01 else
            "HURTING"   if wr_delta <= -2.0 or pnl_delta <= -0.01 else
            "NEUTRAL"
        )

        return {
            "overlay_name": overlay_name,
            "lookback_days": lookback_days,
            "fired":         fired,
            "baseline":      baseline,
            "win_rate_delta": round(wr_delta, 2),
            "pnl_delta":      round(pnl_delta, 4),
            "verdict":        verdict,
        }

    # ── §5 Event Overlay Effectiveness ────────────────────────────────────────

    async def get_event_effectiveness(self, lookback_days: int = 60) -> dict[str, Any]:
        """Compare win-rate for signals with vs without active events."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          CASE WHEN event_adj < 0 THEN 'with_event' ELSE 'no_event' END AS grp,
                          COUNT(*) AS cnt,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct, 0))*100, 4)   AS avg_pnl
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                          AND event_adj IS NOT NULL
                        GROUP BY grp
                        ORDER BY grp
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("overlay_effectiveness.event_query_failed: %s", exc)
            return {"error": str(exc)}

        groups: dict[str, dict] = {}
        for row in rows:
            groups[row[0]] = {
                "count":    int(row[1]),
                "win_rate": float(row[2] or 0),
                "avg_pnl":  float(row[3] or 0),
            }

        with_ev = groups.get("with_event", {"count": 0, "win_rate": 0, "avg_pnl": 0})
        no_ev   = groups.get("no_event",   {"count": 0, "win_rate": 0, "avg_pnl": 0})

        return {
            "lookback_days": lookback_days,
            "with_event":    with_ev,
            "no_event":      no_ev,
            "win_rate_delta": round(with_ev["win_rate"] - no_ev["win_rate"], 2),
            "pnl_delta":      round(with_ev["avg_pnl"] - no_ev["avg_pnl"], 4),
            "note": "Negative delta = event overlay correctly reduced wins in event periods.",
        }

    # ── §6 Regime Stability Overlay Effectiveness ─────────────────────────────

    async def get_regime_stability_report(self, lookback_days: int = 30) -> dict[str, Any]:
        """Win-rate and avg PnL broken down by STABLE / TRANSITION / UNSTABLE."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COALESCE(regime_stability, 'UNKNOWN') AS stability,
                          COUNT(*) AS cnt,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct, 0))*100, 4)   AS avg_pnl,
                          ROUND(AVG(regime_stability_adj), 3) AS avg_adj
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY regime_stability
                        ORDER BY win_rate DESC
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("overlay_effectiveness.regime_stability_query_failed: %s", exc)
            return {"error": str(exc)}

        breakdown = [
            {
                "stability": row[0],
                "count":     int(row[1]),
                "win_rate":  float(row[2] or 0),
                "avg_pnl":   float(row[3] or 0),
                "avg_adj":   float(row[4] or 0),
            }
            for row in rows
        ]

        stable = next((b for b in breakdown if b["stability"] == "STABLE"), None)
        unstable = next((b for b in breakdown if b["stability"] == "UNSTABLE"), None)
        verdict = "INSUFFICIENT_DATA"
        if stable and unstable and stable["count"] >= 10 and unstable["count"] >= 5:
            verdict = "WORKING" if stable["win_rate"] > unstable["win_rate"] else "NOT_WORKING"

        return {
            "lookback_days": lookback_days,
            "breakdown":     breakdown,
            "verdict":        verdict,
        }

    # ── §7 Execution Quality Grade ────────────────────────────────────────────

    async def get_execution_quality_report(self, lookback_days: int = 30) -> dict[str, Any]:
        """Win-rate by execution grade A/B/C/D — confirms grade→quality relationship."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COALESCE(execution_grade, 'UNKNOWN') AS grade,
                          COUNT(*) AS cnt,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                          ROUND(AVG(COALESCE(pnl_pct, current_return_pct, 0))*100, 4)   AS avg_pnl,
                          ROUND(AVG(confidence), 2) AS avg_conf
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                          AND created_at >= :cutoff
                        GROUP BY execution_grade
                        ORDER BY grade
                    """),
                    {"cutoff": cutoff},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("overlay_effectiveness.grade_query_failed: %s", exc)
            return {"error": str(exc)}

        breakdown = [
            {
                "grade":    row[0],
                "count":    int(row[1]),
                "win_rate": float(row[2] or 0),
                "avg_pnl":  float(row[3] or 0),
                "avg_conf": float(row[4] or 0),
            }
            for row in rows
        ]

        # Check monotonicity: A > B > C > D win-rate
        grade_order = ["A", "B", "C", "D"]
        grade_map = {b["grade"]: b["win_rate"] for b in breakdown}
        present = [g for g in grade_order if g in grade_map]
        monotonic = all(
            grade_map[present[i]] >= grade_map[present[i + 1]]
            for i in range(len(present) - 1)
        ) if len(present) >= 2 else None

        return {
            "lookback_days": lookback_days,
            "breakdown":     breakdown,
            "monotonic":     monotonic,
            "note":          "monotonic=True confirms A > B > C win-rate ordering as expected.",
        }

    # ── §8 Correlation Overlay Effectiveness ──────────────────────────────────

    async def get_correlation_effectiveness_report(self, lookback_days: int = 30) -> dict[str, Any]:
        """Compare signals that were correlation-penalised vs baseline."""
        return await self.get_overlay_effectiveness_report(
            "portfolio_correlation", lookback_days=lookback_days
        )

    # ── §15 Validation Milestones ─────────────────────────────────────────────

    async def check_validation_milestones(self) -> dict[str, Any]:
        """Auto-evaluate system at 200/500/1000 completed live trades.

        Returns current completed trade count and per-milestone pass/fail
        for the milestones already reached.
        """
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          COUNT(*) AS total_completed,
                          ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
                          ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,0)) ELSE 0 END), 0)
                          , 3) AS profit_factor,
                          ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 4) AS expectancy
                        FROM signal_analytics
                        WHERE was_accepted = true
                          AND outcome IS NOT NULL
                    """),
                )
                row = r.fetchone()
        except Exception as exc:
            _log.warning("overlay_effectiveness.milestones_query_failed: %s", exc)
            return {"error": str(exc)}

        if row is None:
            return {"total_completed": 0, "milestones": []}

        total  = int(row[0] or 0)
        wr     = float(row[1] or 0)
        pf     = float(row[2] or 0) if row[2] else None
        expct  = float(row[3] or 0)

        milestones = []
        for threshold in _MILESTONE_THRESHOLDS:
            if total < threshold:
                milestones.append({
                    "threshold":    threshold,
                    "reached":      False,
                    "trades_to_go": threshold - total,
                })
                continue

            passed = (
                total >= threshold
                and wr >= 45.0
                and (pf is None or pf >= 1.0)
                and expct >= 0
            )
            milestones.append({
                "threshold":     threshold,
                "reached":       True,
                "passed":        passed,
                "win_rate":      wr,
                "profit_factor": pf,
                "expectancy":    expct,
                "criteria":      {
                    "win_rate_ge_45": wr >= 45.0,
                    "profit_factor_ge_1": pf is None or pf >= 1.0,
                    "positive_expectancy": expct >= 0,
                },
            })

        return {
            "total_completed":   total,
            "current_win_rate":  wr,
            "current_pf":        pf,
            "current_expectancy": expct,
            "milestones":        milestones,
        }
