"""TradeCohortService — Phase 20.6 Sections 1 & 2.

Section 1 — Trade Cohort Engine:
  Groups trades into six cohort dimensions:
    score_bucket    60-64 / 65-69 / 70-74 / 75-79 / 80-84 / 85+
    confidence      <60 / 60-69 / 70-79 / 80-89 / 90+
    mtf             ALIGNED / NEUTRAL / CONFLICT
    regime          direct from regime column
    time_window     09:30-10:30 / 10:30-12:00 / 12:00-13:30 / 13:30-14:30 / 14:30+
    dte             0-DTE / 1-DTE / 2-DTE / 3+-DTE

Section 2 — Cohort Performance Analysis:
  Per-cohort: count, win_rate, profit_factor, sharpe, sortino, expectancy,
              avg_return, avg_mfe, avg_mae, recovery_rate

  Also: top-10 winning cohorts and top-10 losing cohorts across ALL dimensions.

All methods are read-only analytics.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_MIN_COHORT_TRADES = 5   # minimum trades to include a cohort bucket

# Shared aggregate SQL columns — appended after the GROUP BY expression in each query
_PERF_COLS = """
    COUNT(*) AS n,
    ROUND(AVG(CASE WHEN target_hit THEN 1.0 ELSE 0.0 END)*100, 1)          AS win_rate,
    ROUND(
      SUM(CASE WHEN target_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END)
      / NULLIF(SUM(CASE WHEN stop_hit THEN ABS(COALESCE(pnl_pct,current_return_pct,0)) ELSE 0 END), 0)
    ::numeric, 3)                                                            AS profit_factor,
    ROUND(AVG(COALESCE(pnl_pct,current_return_pct))*100, 4)                AS expectancy,
    ROUND(AVG(mfe_pct)*100, 3)                                              AS avg_mfe,
    ROUND(AVG(mae_pct)*100, 3)                                              AS avg_mae,
    ROUND(
      AVG(COALESCE(pnl_pct,current_return_pct))
      / NULLIF(STDDEV(COALESCE(pnl_pct,current_return_pct))::numeric, 0)
      * SQRT(252)
    ::numeric, 3)                                                            AS sharpe,
    ROUND(
      AVG(COALESCE(pnl_pct,current_return_pct))
      / NULLIF(SQRT(AVG(POWER(LEAST(COALESCE(pnl_pct,current_return_pct,0), 0), 2)))::numeric, 0)
      * SQRT(252)
    ::numeric, 3)                                                            AS sortino,
    ROUND(
      CAST(COUNT(*) FILTER (WHERE stop_hit AND mfe_pct > 0.005) AS float)
      / NULLIF(CAST(COUNT(*) FILTER (WHERE stop_hit) AS float), 0) * 100
    ::numeric, 1)                                                            AS recovery_rate
"""

_BASE_WHERE = """
    was_accepted = true
    AND outcome IS NOT NULL
    AND created_at >= :cutoff
"""


def _parse_row(cohort_type: str, bucket: str, row) -> dict:
    """Convert a raw SQL row to a cohort performance dict."""
    def _f(v): return float(v) if v is not None else None
    return {
        "cohort_type":     cohort_type,
        "bucket":          bucket,
        "count":           int(row[0] or 0),
        "win_rate_pct":    _f(row[1]),
        "profit_factor":   _f(row[2]),
        "expectancy_pct":  _f(row[3]),
        "avg_mfe_pct":     _f(row[4]),
        "avg_mae_pct":     _f(row[5]),
        "sharpe":          _f(row[6]),
        "sortino":         _f(row[7]),
        "recovery_rate_pct": _f(row[8]),
        "edge": _classify_edge(_f(row[2]), _f(row[1]), int(row[0] or 0)),
    }


def _classify_edge(pf: float | None, wr: float | None, n: int) -> str:
    if pf is None or wr is None or n < _MIN_COHORT_TRADES:
        return "INSUFFICIENT_DATA"
    if pf >= 1.5 and wr >= 50 and n >= 20:
        return "EDGE_DISCOVERED"
    if pf >= 1.2 or wr >= 47:
        return "EDGE_WEAK"
    return "NO_EDGE"


class TradeCohortService:
    """Cohort grouping and per-cohort performance analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_all_cohorts(self, lookback_days: int = 30) -> dict:
        """Run all 6 cohort queries concurrently and return combined results."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        results = await asyncio.gather(
            self._score_cohorts(cutoff),
            self._confidence_cohorts(cutoff),
            self._mtf_cohorts(cutoff),
            self._regime_cohorts(cutoff),
            self._time_window_cohorts(cutoff),
            self._dte_cohorts(cutoff),
            return_exceptions=True,
        )
        labels = ["score", "confidence", "mtf", "regime", "time_window", "dte"]
        cohorts: dict[str, list] = {}
        for label, result in zip(labels, results):
            cohorts[label] = (
                result if not isinstance(result, Exception)
                else [{"error": str(result)}]
            )

        # Top 10 / Bottom 10 across all dimensions
        all_buckets = [b for dim in cohorts.values() for b in dim if "error" not in b]
        all_buckets_valid = [b for b in all_buckets if b.get("count", 0) >= 10]
        top10 = sorted(all_buckets_valid, key=lambda x: x.get("expectancy_pct") or 0, reverse=True)[:10]
        bot10 = sorted(all_buckets_valid, key=lambda x: x.get("expectancy_pct") or 0)[:10]

        return {
            "lookback_days":         lookback_days,
            "cohorts":               cohorts,
            "top_10_cohorts":        top10,
            "bottom_10_cohorts":     bot10,
            "evaluated_at":          datetime.now(UTC).isoformat(),
        }

    async def get_top_cohorts(self, lookback_days: int = 30, top_n: int = 10) -> dict:
        """Return only the top and bottom N cohorts across all dimensions (fast path)."""
        result = await self.get_all_cohorts(lookback_days)
        return {
            "lookback_days": lookback_days,
            "top_cohorts":   result["top_10_cohorts"][:top_n],
            "bottom_cohorts": result["bottom_10_cohorts"][:top_n],
            "evaluated_at":  result["evaluated_at"],
        }

    # ── Score bucket cohort ───────────────────────────────────────────────────

    async def _score_cohorts(self, cutoff: datetime) -> list[dict]:
        bucket_sql = """
            CASE
              WHEN adjusted_score BETWEEN 60 AND 64 THEN '60-64'
              WHEN adjusted_score BETWEEN 65 AND 69 THEN '65-69'
              WHEN adjusted_score BETWEEN 70 AND 74 THEN '70-74'
              WHEN adjusted_score BETWEEN 75 AND 79 THEN '75-79'
              WHEN adjusted_score BETWEEN 80 AND 84 THEN '80-84'
              WHEN adjusted_score >= 85              THEN '85+'
              ELSE 'OTHER'
            END
        """
        return await self._run_cohort_query("score", bucket_sql, cutoff,
                                            order_col="MIN(adjusted_score)")

    # ── Confidence bucket cohort ──────────────────────────────────────────────

    async def _confidence_cohorts(self, cutoff: datetime) -> list[dict]:
        bucket_sql = """
            CASE
              WHEN confidence < 60                   THEN '<60'
              WHEN confidence BETWEEN 60 AND 69      THEN '60-69'
              WHEN confidence BETWEEN 70 AND 79      THEN '70-79'
              WHEN confidence BETWEEN 80 AND 89      THEN '80-89'
              WHEN confidence >= 90                  THEN '90+'
              ELSE 'OTHER'
            END
        """
        return await self._run_cohort_query("confidence", bucket_sql, cutoff,
                                            order_col="MIN(confidence)")

    # ── MTF alignment cohort ──────────────────────────────────────────────────

    async def _mtf_cohorts(self, cutoff: datetime) -> list[dict]:
        bucket_sql = """
            CASE
              WHEN mtf_alignment IS NULL OR mtf_alignment = 'NEUTRAL' THEN 'NEUTRAL'
              WHEN (direction = 'CE' AND mtf_alignment = 'BULLISH')
                OR (direction = 'PE' AND mtf_alignment = 'BEARISH')  THEN 'ALIGNED'
              ELSE 'CONFLICT'
            END
        """
        return await self._run_cohort_query("mtf", bucket_sql, cutoff,
                                            order_col="AVG(adjusted_score)")

    # ── Regime cohort ─────────────────────────────────────────────────────────

    async def _regime_cohorts(self, cutoff: datetime) -> list[dict]:
        return await self._run_cohort_query("regime", "regime", cutoff,
                                            order_col="AVG(adjusted_score)")

    # ── Time window cohort (IST) ──────────────────────────────────────────────

    async def _time_window_cohorts(self, cutoff: datetime) -> list[dict]:
        # minutes since midnight IST: hour*60 + minute
        bucket_sql = """
            CASE
              WHEN (EXTRACT(HOUR   FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                  + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                   BETWEEN 570 AND 629  THEN '09:30-10:30'
              WHEN (EXTRACT(HOUR   FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                  + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                   BETWEEN 630 AND 719  THEN '10:30-12:00'
              WHEN (EXTRACT(HOUR   FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                  + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                   BETWEEN 720 AND 809  THEN '12:00-13:30'
              WHEN (EXTRACT(HOUR   FROM (created_at AT TIME ZONE 'Asia/Kolkata'))*60
                  + EXTRACT(MINUTE FROM (created_at AT TIME ZONE 'Asia/Kolkata')))
                   BETWEEN 810 AND 869  THEN '13:30-14:30'
              ELSE '14:30+'
            END
        """
        return await self._run_cohort_query("time_window", bucket_sql, cutoff,
                                            order_col="MIN(created_at)")

    # ── DTE cohort ────────────────────────────────────────────────────────────

    async def _dte_cohorts(self, cutoff: datetime) -> list[dict]:
        bucket_sql = """
            CASE
              WHEN dte = 0   THEN '0-DTE'
              WHEN dte = 1   THEN '1-DTE'
              WHEN dte = 2   THEN '2-DTE'
              WHEN dte >= 3  THEN '3+-DTE'
              ELSE 'UNKNOWN'
            END
        """
        return await self._run_cohort_query("dte", bucket_sql, cutoff,
                                            order_col="MIN(dte)")

    # ── Shared query runner ───────────────────────────────────────────────────

    async def _run_cohort_query(
        self,
        cohort_type: str,
        bucket_sql: str,
        cutoff: datetime,
        order_col: str = "COUNT(*)",
    ) -> list[dict]:
        sql = f"""
            SELECT
              ({bucket_sql}) AS bucket,
              {_PERF_COLS}
            FROM signal_analytics
            WHERE {_BASE_WHERE}
              AND adjusted_score IS NOT NULL
            GROUP BY bucket
            HAVING COUNT(*) >= :min_n
            ORDER BY {order_col}
        """
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text(sql),
                    {"cutoff": cutoff, "min_n": _MIN_COHORT_TRADES},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("cohort.%s_error: %s", cohort_type, exc)
            return []

        return [_parse_row(cohort_type, str(row[0]), row[1:]) for row in rows]
