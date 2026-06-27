"""LiveValidationService — Phase 23 §10.

Tracks paper vs live performance separately and generates a drift report.

Deployment stage mapping:
  execution_mode = MANUAL  → PAPER
  execution_mode = AUTOMATIC → LIVE (current default; refined via deployment_stage col later)

Compares:
  Win Rate, Profit Factor, Expectancy, Execution Grade, Avg Slippage proxy,
  Max Drawdown, Data Quality

Significance: two-proportion z-test for win_rate (p < 0.05).
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


def _two_prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    p1 = k1 / n1
    p2 = k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    denom = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    return (p1 - p2) / denom if denom > 0 else 0.0


_PERF_SQL = """
    SELECT
        COUNT(*)                                                           AS n,
        ROUND(AVG(CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END)*100, 2) AS win_rate,
        ROUND(
            SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) /
            NULLIF(ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)), 0),
            3
        )                                                                  AS profit_factor,
        ROUND(AVG(pnl_pct)::numeric, 4)                                   AS expectancy,
        ROUND(AVG(data_quality_score)::numeric, 1)                        AS avg_data_quality,
        SUM(CASE WHEN execution_grade IN ('A','B') THEN 1 ELSE 0 END)    AS ab_grade_n,
        MIN(pnl_pct)                                                       AS worst_trade,
        ROUND(STDDEV_SAMP(pnl_pct)::numeric, 4)                          AS pnl_stddev
    FROM signal_analytics
    WHERE outcome IN ('WIN','LOSS','PARTIAL')
      AND was_accepted = true
      AND pnl_pct IS NOT NULL
      AND {stage_filter}
"""


class LiveValidationService:
    """Compares paper vs live trading performance."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_comparison(
        self,
        days_back: int = 90,
    ) -> dict[str, Any]:
        """Full paper-vs-live comparison with drift significance."""
        since = datetime.now(UTC) - timedelta(days=days_back)

        paper = await self._fetch_stats(
            "COALESCE(deployment_stage, execution_mode) IN ('PAPER', 'MANUAL')",
            since,
        )
        live = await self._fetch_stats(
            "COALESCE(deployment_stage, execution_mode) IN ('LIVE_1LOT','LIVE_2LOT','LIVE_SCALE','AUTOMATIC')",
            since,
        )

        drift_checks = self._compute_drift(paper, live)

        return {
            "paper":        paper,
            "live":         live,
            "drift_checks": drift_checks,
            "period_days":  days_back,
            "has_live_data": live["n"] > 0,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

    async def _fetch_stats(self, stage_filter: str, since: datetime) -> dict[str, Any]:
        sql = _PERF_SQL.format(stage_filter=stage_filter) + " AND created_at >= :since"
        try:
            async with self._sf() as db:
                r = await db.execute(text(sql), {"since": since})
                row = r.fetchone()
        except Exception as exc:
            _log.warning("live_validation.fetch_stats failed: %s", exc)
            return _empty_stats()

        if not row:
            return _empty_stats()

        n    = int(row.n or 0)
        ab_n = int(row.ab_grade_n or 0)
        return {
            "n":               n,
            "win_rate":        float(row.win_rate      or 0),
            "profit_factor":   float(row.profit_factor) if row.profit_factor is not None else None,
            "expectancy":      float(row.expectancy)    if row.expectancy     is not None else None,
            "avg_data_quality":float(row.avg_data_quality or 0),
            "ab_grade_pct":    round(ab_n / n * 100, 1) if n > 0 else 0.0,
            "worst_trade_pct": float(row.worst_trade)   if row.worst_trade    is not None else None,
            "pnl_stddev":      float(row.pnl_stddev)    if row.pnl_stddev     is not None else None,
        }

    def _compute_drift(
        self,
        paper: dict[str, Any],
        live: dict[str, Any],
    ) -> list[dict[str, Any]]:
        checks = []

        def _drift_check(
            metric: str,
            paper_val: float | None,
            live_val: float | None,
            z: float | None = None,
        ) -> dict[str, Any]:
            if paper_val is None or live_val is None:
                return {"metric": metric, "paper": paper_val, "live": live_val,
                        "direction": "UNKNOWN", "significant": False, "z_statistic": None}

            delta = live_val - paper_val
            direction = "IMPROVED" if delta > 0 else ("DEGRADED" if delta < 0 else "UNCHANGED")
            significant = abs(z or 0) >= 1.96

            return {
                "metric":       metric,
                "paper":        round(paper_val, 3),
                "live":         round(live_val, 3),
                "delta":        round(delta, 3),
                "direction":    direction,
                "significant":  significant,
                "z_statistic":  round(z, 3) if z is not None else None,
            }

        # Win rate z-test
        n1, k1 = live["n"],  round((live["win_rate"]  / 100) * live["n"])
        n2, k2 = paper["n"], round((paper["win_rate"] / 100) * paper["n"])
        wr_z   = _two_prop_z(k1, n1, k2, n2)

        checks.append(_drift_check("win_rate_pct",      paper["win_rate"],    live["win_rate"],    wr_z))
        checks.append(_drift_check("profit_factor",     paper["profit_factor"], live["profit_factor"]))
        checks.append(_drift_check("expectancy",        paper["expectancy"],  live["expectancy"]))
        checks.append(_drift_check("ab_grade_pct",      paper["ab_grade_pct"], live["ab_grade_pct"]))
        checks.append(_drift_check("avg_data_quality",  paper["avg_data_quality"], live["avg_data_quality"]))

        return checks


def _empty_stats() -> dict[str, Any]:
    return {
        "n": 0, "win_rate": 0.0, "profit_factor": None,
        "expectancy": None, "avg_data_quality": 0.0,
        "ab_grade_pct": 0.0, "worst_trade_pct": None, "pnl_stddev": None,
    }
