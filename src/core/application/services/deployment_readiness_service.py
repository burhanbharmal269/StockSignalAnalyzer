"""DeploymentReadinessService — Phase 22 §1.

Computes a 0-100 deployment readiness score across 5 weighted categories:
  Infrastructure    (20 pts) — DB, Redis, market data freshness, signal activity
  Strategy          (25 pts) — completed trades, win rate, profit factor, expectancy, CI width
  Execution Quality (15 pts) — execution grade distribution, acceptance rate, fill quality
  Risk              (20 pts) — portfolio heat, drawdown, PANIC events, sector concentration
  Data Quality      (20 pts) — data_quality_score, missing sources, option coverage, VIX availability

Deployment tiers:
  NOT_READY               total < 40
  LIMITED                 40 ≤ total < 60
  READY_FOR_SMALL_CAPITAL 60 ≤ total < 80
  READY_FOR_SCALING       total ≥ 80
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


def _tier(score: int) -> str:
    if score >= 80:
        return "READY_FOR_SCALING"
    if score >= 60:
        return "READY_FOR_SMALL_CAPITAL"
    if score >= 40:
        return "LIMITED"
    return "NOT_READY"


def _wilson_ci_width(k: int, n: int, z: float = 1.96) -> float:
    """Returns width (in percentage points) of Wilson score CI."""
    if n <= 0:
        return 100.0
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    half_w = z * math.sqrt(max(0.0, p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return round(half_w * 2 * 100, 2)


class DeploymentReadinessService:
    """Computes the 0-100 deployment readiness score."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_readiness_score(self) -> dict[str, Any]:
        """Full readiness assessment: score, tier, and per-category breakdown."""
        infra     = await self._score_infrastructure()
        strategy  = await self._score_strategy()
        execution = await self._score_execution()
        risk      = await self._score_risk()
        data_q    = await self._score_data_quality()

        total = (
            infra["score"] + strategy["score"] +
            execution["score"] + risk["score"] + data_q["score"]
        )

        return {
            "total_score":    total,
            "max_score":      100,
            "tier":           _tier(total),
            "categories": {
                "infrastructure":    infra,
                "strategy":          strategy,
                "execution_quality": execution,
                "risk":              risk,
                "data_quality":      data_q,
            },
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    # ── Infrastructure (20 pts) ───────────────────────────────────────────────

    async def _score_infrastructure(self) -> dict[str, Any]:
        checks: dict[str, dict] = {}
        score = 0

        # 1. Database reachable + latency (5 pts)
        try:
            t0 = time.monotonic()
            async with self._sf() as db:
                await db.execute(text("SELECT 1"))
            ms = round((time.monotonic() - t0) * 1000, 1)
            pts = 5 if ms < 100 else (3 if ms < 300 else 1)
            score += pts
            checks["database"] = {"points": pts, "max": 5, "latency_ms": ms, "status": "OK"}
        except Exception as exc:
            checks["database"] = {"points": 0, "max": 5, "status": "FAIL", "error": str(exc)}

        # 2. Redis reachable (5 pts)
        try:
            import redis.asyncio as _aioredis  # type: ignore[import-untyped]
            _url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            _r = _aioredis.from_url(_url, socket_connect_timeout=2)
            t0 = time.monotonic()
            await _r.ping()
            await _r.aclose()
            ms = round((time.monotonic() - t0) * 1000, 1)
            pts = 5 if ms < 50 else (3 if ms < 200 else 1)
            score += pts
            checks["redis"] = {"points": pts, "max": 5, "latency_ms": ms, "status": "OK"}
        except Exception as exc:
            checks["redis"] = {"points": 0, "max": 5, "status": "FAIL", "error": str(exc)}

        # 3. Market data fresh — last market_context_snapshot (5 pts)
        try:
            async with self._sf() as db:
                r = await db.execute(text(
                    "SELECT computed_at FROM market_context_snapshots "
                    "ORDER BY computed_at DESC LIMIT 1"
                ))
                row = r.fetchone()
            if row and row[0]:
                age_min = (datetime.now(UTC) - row[0].replace(tzinfo=UTC)).total_seconds() / 60
                pts = 5 if age_min < 30 else (3 if age_min < 120 else (1 if age_min < 480 else 0))
                score += pts
                checks["market_data"] = {
                    "points":      pts,
                    "max":         5,
                    "age_minutes": round(age_min, 1),
                    "status":      "FRESH" if pts == 5 else ("STALE" if pts > 0 else "VERY_STALE"),
                }
            else:
                checks["market_data"] = {"points": 0, "max": 5, "status": "NO_DATA"}
        except Exception as exc:
            checks["market_data"] = {"points": 0, "max": 5, "status": "FAIL", "error": str(exc)}

        # 4. Signal generation active — last signal in signal_analytics (5 pts)
        try:
            async with self._sf() as db:
                r = await db.execute(text("SELECT MAX(created_at) FROM signal_analytics"))
                row = r.fetchone()
            if row and row[0]:
                age_hr = (datetime.now(UTC) - row[0].replace(tzinfo=UTC)).total_seconds() / 3600
                pts = 5 if age_hr < 1 else (3 if age_hr < 6 else (1 if age_hr < 24 else 0))
                score += pts
                checks["signal_generation"] = {
                    "points":     pts,
                    "max":        5,
                    "age_hours":  round(age_hr, 1),
                    "status":     "ACTIVE" if pts >= 3 else "IDLE",
                }
            else:
                checks["signal_generation"] = {"points": 0, "max": 5, "status": "NO_DATA"}
        except Exception as exc:
            checks["signal_generation"] = {"points": 0, "max": 5, "status": "FAIL", "error": str(exc)}

        return {"score": score, "max": 20, "checks": checks}

    # ── Strategy Validation (25 pts) ──────────────────────────────────────────

    async def _score_strategy(self) -> dict[str, Any]:
        checks: dict[str, dict] = {}
        score = 0

        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*)  AS n,
                        SUM(CASE WHEN target_hit THEN 1 ELSE 0 END)          AS wins,
                        ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_rate,
                        ROUND(
                            SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END) /
                            NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct, 0)) ELSE 0 END), 0)
                        , 3)      AS profit_factor,
                        ROUND(AVG(COALESCE(pnl_pct, 0)) * 100, 4) AS expectancy
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NOT NULL
                """))
                row = r.fetchone()
        except Exception as exc:
            _log.warning("readiness.strategy_query_failed: %s", exc)
            return {"score": 0, "max": 25, "error": str(exc)}

        n     = int(row[0] or 0)
        wins  = int(row[1] or 0)
        wr    = float(row[2] or 0)
        pf    = float(row[3]) if row[3] else None
        expct = float(row[4] or 0)
        ci_w  = _wilson_ci_width(wins, n)

        # Completed trades (5 pts)
        pts_n = 0 if n == 0 else (1 if n < 10 else (2 if n < 50 else (3 if n < 200 else (4 if n < 500 else 5))))
        score += pts_n
        checks["completed_trades"] = {"points": pts_n, "max": 5, "value": n}

        # Win rate (5 pts, only scored with ≥10 trades)
        if n >= 10:
            pts_wr = 5 if wr >= 52 else (4 if wr >= 48 else (3 if wr >= 44 else (2 if wr >= 40 else 0)))
        else:
            pts_wr = 0
        score += pts_wr
        checks["win_rate"] = {"points": pts_wr, "max": 5, "value": round(wr, 2), "sample": n}

        # Profit factor (5 pts)
        if n >= 10 and pf is not None:
            pts_pf = 5 if pf >= 1.5 else (4 if pf >= 1.2 else (2 if pf >= 1.0 else (1 if pf >= 0.8 else 0)))
        else:
            pts_pf = 0
        score += pts_pf
        checks["profit_factor"] = {"points": pts_pf, "max": 5, "value": round(pf, 3) if pf else None, "sample": n}

        # Expectancy (5 pts)
        if n >= 10:
            pts_exp = 5 if expct > 0 else (2 if expct == 0 else 0)
        else:
            pts_exp = 0
        score += pts_exp
        checks["expectancy"] = {"points": pts_exp, "max": 5, "value": round(expct, 4), "sample": n}

        # CI width — narrow = more data, more confidence (5 pts)
        if n >= 10:
            pts_ci = 5 if ci_w < 10 else (4 if ci_w < 20 else (2 if ci_w < 30 else 1))
        else:
            pts_ci = 0
        score += pts_ci
        checks["ci_width"] = {
            "points": pts_ci, "max": 5,
            "value":  round(ci_w, 2),
            "note":   "Width of 95% CI for win rate — narrower = more data",
        }

        return {"score": score, "max": 25, "checks": checks}

    # ── Execution Quality (15 pts) ────────────────────────────────────────────

    async def _score_execution(self) -> dict[str, Any]:
        checks: dict[str, dict] = {}
        score = 0

        try:
            async with self._sf() as db:
                # Grade A/B rate from last 200 accepted signals
                r = await db.execute(text("""
                    SELECT execution_grade, COUNT(*) AS n
                    FROM (
                        SELECT execution_grade FROM signal_analytics
                        WHERE was_accepted = true AND execution_grade IS NOT NULL
                        ORDER BY created_at DESC LIMIT 200
                    ) recent
                    GROUP BY execution_grade
                """))
                grade_rows = r.fetchall()

                # Acceptance rate from last 500 signals
                r2 = await db.execute(text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted
                    FROM (
                        SELECT was_accepted FROM signal_analytics
                        ORDER BY created_at DESC LIMIT 500
                    ) recent
                """))
                acc_row = r2.fetchone()
        except Exception as exc:
            _log.warning("readiness.execution_query_failed: %s", exc)
            return {"score": 5, "max": 15, "error": str(exc)}

        # Grade distribution (5 pts)
        grade_counts: dict[str, int] = {row[0]: int(row[1]) for row in grade_rows if row[0]}
        total_graded = sum(grade_counts.values())
        ab_rate = (
            (grade_counts.get("A", 0) + grade_counts.get("B", 0)) / total_graded * 100
            if total_graded > 0 else 0.0
        )
        pts_grade = (5 if ab_rate >= 70 else 3 if ab_rate >= 50 else 1 if ab_rate >= 30 else 0) if total_graded > 0 else 5
        score += pts_grade
        checks["execution_grade"] = {
            "points": pts_grade, "max": 5,
            "ab_rate_pct": round(ab_rate, 1),
            "distribution": grade_counts,
        }

        # Acceptance rate (5 pts)
        total_sigs = int(acc_row[0] or 0)
        accepted   = int(acc_row[1] or 0)
        acc_rate   = (accepted / total_sigs * 100) if total_sigs > 0 else None
        pts_acc = (
            5 if acc_rate is None else
            5 if acc_rate >= 60 else
            3 if acc_rate >= 40 else
            1 if acc_rate >= 15 else 0
        )
        score += pts_acc
        checks["acceptance_rate"] = {
            "points": pts_acc, "max": 5,
            "value_pct": round(acc_rate, 1) if acc_rate is not None else None,
        }

        # Fill quality from execution_analytics (5 pts, graceful if table absent)
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT COUNT(*) AS fills,
                           ROUND(AVG(NULLIF(slippage_bps, 0)), 2) AS avg_slip
                    FROM execution_analytics
                    WHERE recorded_at >= NOW() - INTERVAL '30 days'
                """))
                ea = r.fetchone()
            fills    = int(ea[0] or 0)
            avg_slip = float(ea[1]) if ea[1] else None
            pts_fill = 5 if fills > 0 and (avg_slip is None or avg_slip < 10) else (3 if fills > 0 else 5)
            checks["fill_quality"] = {
                "points": pts_fill, "max": 5,
                "fills_30d": fills, "avg_slippage_bps": avg_slip,
            }
        except Exception:
            pts_fill = 5
            checks["fill_quality"] = {"points": 5, "max": 5, "note": "execution_analytics unavailable"}
        score += pts_fill

        return {"score": score, "max": 15, "checks": checks}

    # ── Risk (20 pts) ─────────────────────────────────────────────────────────

    async def _score_risk(self) -> dict[str, Any]:
        checks: dict[str, dict] = {}
        score = 0

        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT COUNT(*) AS open_signals
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NULL
                      AND created_at >= NOW() - INTERVAL '1 day'
                """))
                heat_row = r.fetchone()

                r2 = await db.execute(text("""
                    SELECT ROUND(MIN(dp) * 100, 4)  AS max_daily_loss_pct,
                           ROUND(SUM(CASE WHEN dp < 0 THEN dp ELSE 0 END) * 100, 4) AS total_loss_pct
                    FROM (
                        SELECT DATE(created_at AT TIME ZONE 'UTC') AS d,
                               SUM(COALESCE(pnl_pct, 0)) AS dp
                        FROM signal_analytics
                        WHERE was_accepted = true AND outcome IS NOT NULL
                          AND created_at >= NOW() - INTERVAL '30 days'
                        GROUP BY d
                    ) daily
                """))
                dd_row = r2.fetchone()

                r3 = await db.execute(text("""
                    SELECT COUNT(*) FROM signal_analytics
                    WHERE market_context = 'PANIC'
                      AND created_at >= NOW() - INTERVAL '7 days'
                """))
                panic_row = r3.fetchone()

                r4 = await db.execute(text("""
                    SELECT sector, COUNT(*) * 100.0 /
                           NULLIF((
                               SELECT COUNT(*) FROM signal_analytics
                               WHERE was_accepted = true AND outcome IS NULL
                                 AND created_at >= NOW() - INTERVAL '1 day'
                           ), 0) AS pct
                    FROM signal_analytics
                    WHERE was_accepted = true AND outcome IS NULL
                      AND created_at >= NOW() - INTERVAL '1 day'
                      AND sector IS NOT NULL
                    GROUP BY sector
                    ORDER BY pct DESC
                    LIMIT 1
                """))
                conc_row = r4.fetchone()
        except Exception as exc:
            _log.warning("readiness.risk_query_failed: %s", exc)
            return {"score": 10, "max": 20, "error": str(exc)}

        # Portfolio heat (5 pts)
        open_n = int(heat_row[0] or 0)
        pts_h = 5 if open_n <= 5 else (4 if open_n <= 10 else (2 if open_n <= 15 else 0))
        score += pts_h
        checks["portfolio_heat"] = {"points": pts_h, "max": 5, "open_signals": open_n}

        # Drawdown (5 pts)
        total_loss = abs(float(dd_row[1] or 0))
        pts_dd = 5 if total_loss < 3 else (4 if total_loss < 7 else (2 if total_loss < 12 else (1 if total_loss < 20 else 0)))
        score += pts_dd
        checks["drawdown"] = {"points": pts_dd, "max": 5, "total_loss_30d_pct": round(total_loss, 2)}

        # PANIC events in last 7 days (5 pts)
        panic_n = int(panic_row[0] or 0)
        pts_p = 5 if panic_n == 0 else (2 if panic_n <= 3 else 0)
        score += pts_p
        checks["panic_events"] = {"points": pts_p, "max": 5, "panic_signals_7d": panic_n}

        # Sector concentration (5 pts)
        max_sec = float(conc_row[1]) if conc_row and conc_row[1] else 0.0
        pts_c = 5 if max_sec < 40 else (3 if max_sec < 60 else (1 if max_sec < 80 else 0))
        score += pts_c
        checks["sector_concentration"] = {
            "points": pts_c, "max": 5,
            "max_sector_pct": round(max_sec, 1),
            "sector": conc_row[0] if conc_row else None,
        }

        return {"score": score, "max": 20, "checks": checks}

    # ── Data Quality (20 pts) ─────────────────────────────────────────────────

    async def _score_data_quality(self) -> dict[str, Any]:
        checks: dict[str, dict] = {}
        score = 0

        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                        ROUND(AVG(COALESCE(data_quality_score, 0)), 4) AS avg_dq,
                        ROUND(
                            AVG(CASE WHEN missing_sources IS NOT NULL AND missing_sources != '[]' THEN 1.0 ELSE 0.0 END),
                            4
                        ) AS missing_rate,
                        ROUND(
                            SUM(CASE WHEN option_type IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0),
                            2
                        ) AS opt_coverage,
                        COUNT(*) AS total
                    FROM signal_analytics
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                """))
                dq_row = r.fetchone()

                r2 = await db.execute(text("""
                    SELECT COUNT(*) FROM market_context_snapshots
                    WHERE computed_at >= NOW() - INTERVAL '1 day'
                      AND vix IS NOT NULL
                """))
                vix_row = r2.fetchone()
        except Exception as exc:
            _log.warning("readiness.data_quality_query_failed: %s", exc)
            return {"score": 10, "max": 20, "error": str(exc)}

        avg_dq   = float(dq_row[0] or 0)
        miss_pct = float(dq_row[1] or 0) * 100
        opt_cov  = float(dq_row[2] or 0)
        total    = int(dq_row[3] or 0)
        vix_n    = int(vix_row[0] or 0)

        # Avg data quality score (5 pts)
        pts_dq = 5 if avg_dq >= 0.90 else (4 if avg_dq >= 0.80 else (2 if avg_dq >= 0.70 else 1))
        score += pts_dq
        checks["data_quality_score"] = {"points": pts_dq, "max": 5, "value": round(avg_dq, 3), "sample": total}

        # Missing sources rate (5 pts)
        pts_m = 5 if miss_pct < 5 else (4 if miss_pct < 15 else (2 if miss_pct < 30 else 0))
        score += pts_m
        checks["missing_sources"] = {"points": pts_m, "max": 5, "rate_pct": round(miss_pct, 1)}

        # Option chain coverage (5 pts)
        pts_o = 5 if opt_cov >= 80 else (3 if opt_cov >= 60 else (1 if opt_cov >= 30 else 0))
        score += pts_o
        checks["option_chain_coverage"] = {"points": pts_o, "max": 5, "coverage_pct": round(opt_cov, 1)}

        # VIX data availability (5 pts)
        pts_v = 5 if vix_n >= 10 else (3 if vix_n >= 1 else 0)
        score += pts_v
        checks["vix_data"] = {"points": pts_v, "max": 5, "snapshots_24h": vix_n}

        return {"score": score, "max": 20, "checks": checks}
