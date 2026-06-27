"""CohortEngineService — Phase 23 §3.

Assigns every completed trade to multiple research cohorts and computes
per-cohort performance statistics.

Dimensions supported:
  score_bucket       60-64 / 65-69 / 70-74 / 75-79 / 80-84 / 85+
  confidence_bucket  55-60 / 60-65 / 65-70 / 70-75 / 75+
  regime             existing regime column values
  instrument_type    NIFTY / BANKNIFTY / FINNIFTY / STOCK_OPTIONS / OTHER_INDEX
  time_window        09:15-10:00 / 10:00-11:30 / 11:30-13:00 / 13:00-14:30 / 14:30-15:30
  day_of_week        Monday … Friday
  dte_bucket         0 / 1 / 2 / 3+
  market_context     NORMAL / CAUTION / HIGH_RISK / PANIC
  qualification_grade A+ / A / B / C / D

All queries run only on completed trades (outcome IN ('WIN','LOSS','PARTIAL')).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# IST offset applied via AT TIME ZONE 'Asia/Kolkata' (IMMUTABLE in PostgreSQL)
_IST_TZ = "Asia/Kolkata"

# SQL expression fragments that classify a row into a named bucket.
# Each produces a VARCHAR value usable in GROUP BY.
_DIM_SQL: dict[str, str] = {
    "score_bucket": """
        CASE
            WHEN adjusted_score < 65 THEN '60-64'
            WHEN adjusted_score < 70 THEN '65-69'
            WHEN adjusted_score < 75 THEN '70-74'
            WHEN adjusted_score < 80 THEN '75-79'
            WHEN adjusted_score < 85 THEN '80-84'
            ELSE '85+'
        END
    """,

    "confidence_bucket": """
        CASE
            WHEN confidence < 60 THEN '55-60'
            WHEN confidence < 65 THEN '60-65'
            WHEN confidence < 70 THEN '65-70'
            WHEN confidence < 75 THEN '70-75'
            ELSE '75+'
        END
    """,

    "regime": "COALESCE(regime, 'UNKNOWN')",

    "instrument_type": """
        CASE
            WHEN ticker IN ('NIFTY','NIFTY50','NIFTY 50') THEN 'NIFTY'
            WHEN ticker LIKE 'BANKNIFTY%' OR ticker = 'NIFTY BANK' THEN 'BANKNIFTY'
            WHEN ticker LIKE 'FINNIFTY%' OR ticker = 'NIFTY FIN SERVICE' THEN 'FINNIFTY'
            WHEN is_index = true THEN 'OTHER_INDEX'
            ELSE 'STOCK_OPTIONS'
        END
    """,

    "time_window": f"""
        CASE
            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE '{_IST_TZ}')) * 60 +
                  EXTRACT(MINUTE FROM (created_at AT TIME ZONE '{_IST_TZ}')))
                 BETWEEN 555 AND 599 THEN '09:15-10:00'
            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE '{_IST_TZ}')) * 60 +
                  EXTRACT(MINUTE FROM (created_at AT TIME ZONE '{_IST_TZ}')))
                 BETWEEN 600 AND 689 THEN '10:00-11:30'
            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE '{_IST_TZ}')) * 60 +
                  EXTRACT(MINUTE FROM (created_at AT TIME ZONE '{_IST_TZ}')))
                 BETWEEN 690 AND 779 THEN '11:30-13:00'
            WHEN (EXTRACT(HOUR FROM (created_at AT TIME ZONE '{_IST_TZ}')) * 60 +
                  EXTRACT(MINUTE FROM (created_at AT TIME ZONE '{_IST_TZ}')))
                 BETWEEN 780 AND 869 THEN '13:00-14:30'
            ELSE '14:30-15:30'
        END
    """,

    "day_of_week": f"""
        TO_CHAR(created_at AT TIME ZONE '{_IST_TZ}', 'Day')
    """,

    "dte_bucket": """
        CASE
            WHEN dte = 0 THEN '0'
            WHEN dte = 1 THEN '1'
            WHEN dte = 2 THEN '2'
            ELSE '3+'
        END
    """,

    "market_context": "COALESCE(market_context, 'UNKNOWN')",

    "qualification_grade": "COALESCE(qualification_grade, 'UNGRADED')",
}

_STATS_SQL = """
    COUNT(*)                                                    AS trade_count,
    ROUND(AVG(CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END)*100, 2)   AS win_rate,
    ROUND(
        SUM(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE 0 END) /
        NULLIF(ABS(SUM(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE 0 END)), 0),
        3
    )                                                           AS profit_factor,
    ROUND(AVG(pnl_pct)::numeric, 4)                            AS expectancy,
    ROUND(
        (AVG(pnl_pct) / NULLIF(STDDEV_SAMP(pnl_pct), 0))::numeric,
        3
    )                                                           AS sharpe,
    ROUND(
        (AVG(pnl_pct) /
         NULLIF(STDDEV_SAMP(CASE WHEN pnl_pct < 0 THEN pnl_pct END), 0))::numeric,
        3
    )                                                           AS sortino,
    ROUND(AVG(mfe_pct)::numeric, 4)                            AS avg_mfe,
    ROUND(AVG(mae_pct)::numeric, 4)                            AS avg_mae,
    ROUND(AVG(adjusted_score)::numeric, 2)                     AS avg_score,
    ROUND(AVG(confidence)::numeric, 2)                         AS avg_confidence,
    ROUND(AVG(data_quality_score)::numeric, 1)                 AS avg_data_quality
"""

_BASE_WHERE = """
    WHERE outcome IN ('WIN', 'LOSS', 'PARTIAL')
      AND was_accepted = true
      AND pnl_pct IS NOT NULL
"""


class CohortEngineService:
    """Computes per-cohort performance for all supported dimensions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_cohort_stats(
        self,
        dimension: str,
        min_trades: int = 10,
        days_back: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return win rate / PF / expectancy stats for every cohort in one dimension."""
        if dimension not in _DIM_SQL:
            raise ValueError(f"Unknown dimension '{dimension}'. Valid: {list(_DIM_SQL)}")

        dim_expr = _DIM_SQL[dimension]
        date_filter = ""
        params: dict[str, Any] = {"min_trades": min_trades}
        if days_back:
            date_filter = "AND created_at >= NOW() - INTERVAL ':days days'"
            params["days"] = days_back

        sql = f"""
            SELECT
                ({dim_expr}) AS cohort,
                {_STATS_SQL}
            FROM signal_analytics
            {_BASE_WHERE}
            {date_filter}
            GROUP BY 1
            HAVING COUNT(*) >= :min_trades
            ORDER BY profit_factor DESC NULLS LAST
        """
        try:
            async with self._sf() as db:
                r = await db.execute(text(sql), params)
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("cohort_engine.%s failed: %s", dimension, exc)
            return []

        return [_row_to_dict(row, "cohort") for row in rows]

    async def get_all_cohort_summaries(self, min_trades: int = 5) -> dict[str, Any]:
        """Fetch top 5 cohorts for every dimension — used by research command center."""
        summaries: dict[str, Any] = {}
        for dim in _DIM_SQL:
            try:
                rows = await self.get_cohort_stats(dim, min_trades=min_trades)
                summaries[dim] = rows[:10]
            except Exception as exc:
                _log.warning("cohort_engine.summary.%s failed: %s", dim, exc)
                summaries[dim] = []
        return summaries

    async def get_top_and_bottom(
        self,
        dimension: str,
        n: int = 3,
        min_trades: int = 10,
    ) -> dict[str, Any]:
        """Return top-N and bottom-N cohorts by profit factor for a dimension."""
        all_rows = await self.get_cohort_stats(dimension, min_trades=min_trades)
        return {
            "dimension": dimension,
            "top": all_rows[:n],
            "bottom": list(reversed(all_rows[-n:])) if len(all_rows) >= n else all_rows,
        }


def _row_to_dict(row: Any, group_col: str) -> dict[str, Any]:
    return {
        "cohort":         getattr(row, group_col, None),
        "trade_count":    int(row.trade_count or 0),
        "win_rate":       float(row.win_rate or 0),
        "profit_factor":  float(row.profit_factor) if row.profit_factor is not None else None,
        "expectancy":     float(row.expectancy)     if row.expectancy     is not None else None,
        "sharpe":         float(row.sharpe)         if row.sharpe         is not None else None,
        "sortino":        float(row.sortino)        if row.sortino        is not None else None,
        "avg_mfe":        float(row.avg_mfe)        if row.avg_mfe        is not None else None,
        "avg_mae":        float(row.avg_mae)        if row.avg_mae        is not None else None,
        "avg_score":      float(row.avg_score or 0),
        "avg_confidence": float(row.avg_confidence or 0),
        "avg_data_quality": float(row.avg_data_quality or 0),
    }
