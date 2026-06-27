"""StrategyHealthService — Phase 23 §6.

Produces a single 0–100 health score across 8 categories with a 7-day trend.

Categories and weights:
  Architecture   (10%) — zero HIGH bug detections
  Signal Engine  (15%) — scanner active, acceptance rate reasonable
  Execution      (10%) — grade A/B rate, fill quality
  Data Quality   (15%) — avg data_quality_score, missing sources rate
  Risk           (15%) — drawdown, heat, PANIC events
  Validation     (15%) — Phase 22 deployment readiness score
  Research       (10%) — qualification coverage, cohort data sufficiency
  Deployment     (10%) — highest go/no-go gate achieved

Output:
  {
    "overall": 74,
    "trend": "IMPROVING",          # IMPROVING / STABLE / DECLINING
    "categories": {
        "architecture": {"score": 90, "weight": 0.10, "details": {...}},
        ...
    },
    "evaluated_at": "..."
  }
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_WEIGHTS = {
    "architecture":  0.10,
    "signal_engine": 0.15,
    "execution":     0.10,
    "data_quality":  0.15,
    "risk":          0.15,
    "validation":    0.15,
    "research":      0.10,
    "deployment":    0.10,
}

_SAMPLE = 200   # rows to inspect for recent-signal stats


class StrategyHealthService:
    """Computes the unified platform health score."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        deployment_readiness_service: Any | None = None,
        bug_detection_service: Any | None = None,
        go_no_go_service: Any | None = None,
    ) -> None:
        self._sf          = session_factory
        self._readiness   = deployment_readiness_service
        self._bugs        = bug_detection_service
        self._go_no_go    = go_no_go_service

    async def get_health_score(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        categories = await self._compute_categories()

        overall = round(
            sum(v["score"] * _WEIGHTS[k] for k, v in categories.items()),
            1,
        )

        trend = await self._compute_trend(overall)

        return {
            "overall":      overall,
            "trend":        trend,
            "categories":   categories,
            "evaluated_at": now.isoformat(),
        }

    async def _compute_categories(self) -> dict[str, Any]:
        cats: dict[str, Any] = {}

        # ── Architecture ──────────────────────────────────────────────────────
        arch_score = 100
        arch_details: dict = {}
        if self._bugs:
            try:
                bug_report = await self._bugs.run_all_checks(sample_n=_SAMPLE)
                high_n = bug_report["summary"]["high_severity"]
                detected_n = bug_report["summary"]["detected"]
                arch_score = max(0, 100 - high_n * 25 - (detected_n - high_n) * 10)
                arch_details = {"high_bugs": high_n, "total_bugs": detected_n}
            except Exception:
                pass
        cats["architecture"] = {"score": arch_score, "weight": _WEIGHTS["architecture"],
                                 "details": arch_details}

        # ── Signal Engine ──────────────────────────────────────────────────────
        se_score, se_details = await self._score_signal_engine()
        cats["signal_engine"] = {"score": se_score, "weight": _WEIGHTS["signal_engine"],
                                  "details": se_details}

        # ── Execution ─────────────────────────────────────────────────────────
        ex_score, ex_details = await self._score_execution()
        cats["execution"] = {"score": ex_score, "weight": _WEIGHTS["execution"],
                              "details": ex_details}

        # ── Data Quality ──────────────────────────────────────────────────────
        dq_score, dq_details = await self._score_data_quality()
        cats["data_quality"] = {"score": dq_score, "weight": _WEIGHTS["data_quality"],
                                 "details": dq_details}

        # ── Risk ──────────────────────────────────────────────────────────────
        ri_score, ri_details = await self._score_risk()
        cats["risk"] = {"score": ri_score, "weight": _WEIGHTS["risk"], "details": ri_details}

        # ── Validation (uses Phase 22 readiness) ─────────────────────────────
        val_score = 50
        val_details: dict = {}
        if self._readiness:
            try:
                rd = await self._readiness.get_readiness()
                val_score  = min(100, rd.get("overall_score", 50))
                val_details = {"readiness_score": rd.get("overall_score"), "tier": rd.get("tier")}
            except Exception:
                pass
        cats["validation"] = {"score": val_score, "weight": _WEIGHTS["validation"],
                               "details": val_details}

        # ── Research ─────────────────────────────────────────────────────────
        re_score, re_details = await self._score_research()
        cats["research"] = {"score": re_score, "weight": _WEIGHTS["research"],
                             "details": re_details}

        # ── Deployment ────────────────────────────────────────────────────────
        dep_score = 0
        dep_details: dict = {}
        if self._go_no_go:
            try:
                readiness_score = 0
                if self._readiness:
                    rd = await self._readiness.get_readiness()
                    readiness_score = rd.get("overall_score", 0)
                gng = await self._go_no_go.evaluate(readiness_score)
                highest = gng.get("highest_gate_passed")
                gate_map = {"NONE": 0, "GATE_1": 25, "GATE_2": 50, "GATE_3": 75, "GATE_4": 100}
                dep_score   = gate_map.get(highest or "NONE", 0)
                dep_details = {"highest_gate": highest, "top_recommendation": gng.get("top_recommendation")}
            except Exception:
                pass
        cats["deployment"] = {"score": dep_score, "weight": _WEIGHTS["deployment"],
                               "details": dep_details}

        return cats

    async def _score_signal_engine(self) -> tuple[int, dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        MAX(created_at)                                            AS last_signal,
                        COUNT(*)                                                   AS total,
                        SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END)             AS accepted
                    FROM (SELECT created_at, was_accepted FROM signal_analytics
                          ORDER BY created_at DESC LIMIT :n) rec
                """), {"n": _SAMPLE})
                row = r.fetchone()

            if not row or not row.last_signal:
                return 0, {"error": "no signals found"}

            age_min = (datetime.now(UTC) - row.last_signal.replace(tzinfo=UTC)).total_seconds() / 60
            total   = int(row.total or 0)
            accepted = int(row.accepted or 0)
            accept_rate = (accepted / total * 100) if total > 0 else 0

            scanner_score  = max(0, 100 - int(age_min / 2))   # -1 pt per 2 min stale
            rate_score     = min(100, int(accept_rate * 3))    # 33% acceptance → 100
            score = int((scanner_score * 0.6 + rate_score * 0.4))
            return min(100, score), {
                "age_minutes": round(age_min, 1),
                "acceptance_rate_pct": round(accept_rate, 1),
                "sample_n": total,
            }
        except Exception as exc:
            _log.debug("health.signal_engine failed: %s", exc)
            return 50, {}

    async def _score_execution(self) -> tuple[int, dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN execution_grade IN ('A','B') THEN 1 ELSE 0 END) AS ab_n,
                        SUM(CASE WHEN execution_grade = 'D' THEN 1 ELSE 0 END)        AS d_n
                    FROM (SELECT execution_grade FROM signal_analytics
                          WHERE was_accepted = true AND execution_grade IS NOT NULL
                          ORDER BY created_at DESC LIMIT :n) rec
                """), {"n": _SAMPLE})
                row = r.fetchone()

            total = int(row.total or 0)
            if total == 0:
                return 50, {"note": "no graded signals yet"}
            ab_pct = float(row.ab_n or 0) / total * 100
            d_pct  = float(row.d_n  or 0) / total * 100
            score  = max(0, int(ab_pct * 0.8 - d_pct * 0.4))
            return min(100, score), {"ab_grade_pct": round(ab_pct, 1), "d_grade_pct": round(d_pct, 1)}
        except Exception as exc:
            _log.debug("health.execution failed: %s", exc)
            return 50, {}

    async def _score_data_quality(self) -> tuple[int, dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        AVG(data_quality_score)                                        AS avg_dq,
                        SUM(CASE WHEN missing_sources IS NOT NULL THEN 1 ELSE 0 END)  AS missing_n,
                        COUNT(*)                                                        AS total
                    FROM (SELECT data_quality_score, missing_sources FROM signal_analytics
                          ORDER BY created_at DESC LIMIT :n) rec
                    WHERE data_quality_score IS NOT NULL
                """), {"n": _SAMPLE})
                row = r.fetchone()

            avg_dq  = float(row.avg_dq   or 0)
            total   = int(row.total      or 0)
            miss_n  = int(row.missing_n  or 0)
            miss_rt = (miss_n / total * 100) if total > 0 else 0
            score   = max(0, int(avg_dq - miss_rt * 0.5))
            return min(100, score), {"avg_data_quality": round(avg_dq, 1), "missing_sources_pct": round(miss_rt, 1)}
        except Exception as exc:
            _log.debug("health.data_quality failed: %s", exc)
            return 50, {}

    async def _score_risk(self) -> tuple[int, dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        SUM(CASE WHEN market_context = 'PANIC' AND created_at >= NOW()-INTERVAL '7 days'
                                 THEN 1 ELSE 0 END) AS panic_7d,
                        MIN(CASE WHEN outcome = 'LOSS' AND pnl_pct IS NOT NULL
                                 THEN pnl_pct END)  AS worst_pnl,
                        COUNT(CASE WHEN outcome IS NULL AND was_accepted = true
                                   AND created_at >= NOW()-INTERVAL '1 day'
                                   THEN 1 END)      AS open_signals
                    FROM signal_analytics
                """))
                row = r.fetchone()

            panic7   = int(row.panic_7d   or 0)
            worst    = float(row.worst_pnl or 0)
            open_sig = int(row.open_signals or 0)

            score = 100
            score -= panic7 * 15             # -15 per PANIC event in 7d
            score -= max(0, abs(worst) * 5)  # -5 per 1% worst loss
            score -= min(30, open_sig * 3)   # -3 per open signal (cap 30)
            return max(0, min(100, int(score))), {
                "panic_events_7d": panic7,
                "worst_loss_pct": round(worst, 2),
                "open_signals_today": open_sig,
            }
        except Exception as exc:
            _log.debug("health.risk failed: %s", exc)
            return 70, {}

    async def _score_research(self) -> tuple[int, dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*)                                                         AS total_accepted,
                        SUM(CASE WHEN qualification_grade IS NOT NULL THEN 1 ELSE 0 END) AS graded_n,
                        COUNT(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL') THEN 1 END)  AS completed
                    FROM signal_analytics
                    WHERE was_accepted = true
                """))
                row = r.fetchone()

            total     = int(row.total_accepted or 0)
            graded    = int(row.graded_n or 0)
            completed = int(row.completed or 0)

            coverage_pct = (graded / total * 100) if total > 0 else 0
            data_score   = min(100, int(completed / 5))   # 500 trades → 100

            score = int(coverage_pct * 0.5 + data_score * 0.5)
            return min(100, score), {
                "qualification_coverage_pct": round(coverage_pct, 1),
                "completed_trades": completed,
                "total_accepted": total,
            }
        except Exception as exc:
            _log.debug("health.research failed: %s", exc)
            return 10, {}

    async def _compute_trend(self, current_overall: float) -> str:
        """Compare today's health to 7 days ago."""
        try:
            seven_days_ago = datetime.now(UTC) - timedelta(days=7)
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT AVG(data_quality_score) AS avg_dq,
                           SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS acc,
                           COUNT(*) AS tot
                    FROM signal_analytics
                    WHERE created_at BETWEEN :start AND :end
                """), {
                    "start": seven_days_ago,
                    "end":   seven_days_ago + timedelta(days=1),
                })
                row = r.fetchone()

            if not row or not row.tot:
                return "STABLE"
            # Proxy: use acceptance rate + avg data quality as a crude prior-week health
            prior_acc_rate  = (float(row.acc or 0) / int(row.tot) * 100)
            prior_dq        = float(row.avg_dq or 0)
            prior_proxy     = (prior_acc_rate * 0.5 + prior_dq * 0.5)

            # We don't store prior overall, so use proxy delta as signal
            delta = current_overall - prior_proxy
            if delta > 5:
                return "IMPROVING"
            if delta < -5:
                return "DECLINING"
            return "STABLE"
        except Exception:
            return "STABLE"
