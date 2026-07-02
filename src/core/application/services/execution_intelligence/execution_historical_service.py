"""ExecutionHistoricalService — Phase 23 §13.

Provides rolling historical analytics across configurable windows:
  1D / 7D / 30D / 90D / Lifetime

Aggregates:
  - Execution speed (avg, P95, max total_execution_ms)
  - Slippage (avg entry/exit, total)
  - Fill quality (avg score, fill_pct)
  - Rejection rate
  - Retry rate
  - Broker health average
  - Volume (signal count)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_WINDOWS: dict[str, str] = {
    "1d":       "1 day",
    "7d":       "7 days",
    "30d":      "30 days",
    "90d":      "90 days",
    "lifetime": None,  # no time filter
}


class ExecutionHistoricalService:
    """Aggregates rolling execution stats. Fail-open."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_window_stats(self, window: str = "7d") -> dict[str, Any]:
        """Return execution stats for a named window (1d/7d/30d/90d/lifetime)."""
        interval = _WINDOWS.get(window)
        time_filter = f"recorded_at > NOW() - INTERVAL '{interval}'" if interval else "TRUE"
        event_filter = f"signal_generated_at > NOW() - INTERVAL '{interval}'" if interval else "TRUE"

        try:
            async with self._sf() as db:
                # Execution speed (from execution_events)
                r = await db.execute(text(f"""
                    SELECT
                        COUNT(*) AS signal_count,
                        AVG(total_execution_ms) AS avg_exec_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_execution_ms) AS p95_exec_ms,
                        MAX(total_execution_ms) AS max_exec_ms
                    FROM execution_events
                    WHERE {event_filter}
                      AND total_execution_ms IS NOT NULL
                """))
                speed = dict(r.mappings().fetchone() or {})

                # Slippage stats
                r2 = await db.execute(text(f"""
                    SELECT
                        COUNT(*) AS orders_with_slippage,
                        AVG(entry_slippage_pct) AS avg_entry_slip_pct,
                        AVG(total_slippage_pct) AS avg_total_slip_pct,
                        AVG(total_slippage_rupees) AS avg_slip_inr
                    FROM execution_slippage
                    WHERE {time_filter}
                """))
                slippage = dict(r2.mappings().fetchone() or {})

                # Fill quality
                r3 = await db.execute(text(f"""
                    SELECT
                        AVG(execution_quality_score) AS avg_quality_score,
                        AVG(fill_pct) AS avg_fill_pct,
                        AVG(partial_fills) AS avg_partials
                    FROM execution_metrics
                    WHERE {time_filter}
                """))
                quality = dict(r3.mappings().fetchone() or {})

                # Rejection rate
                r4 = await db.execute(text(f"""
                    SELECT
                        COUNT(*) AS total_rejections,
                        COUNT(DISTINCT category) AS distinct_categories
                    FROM execution_rejections
                    WHERE {time_filter}
                """))
                rejections = dict(r4.mappings().fetchone() or {})

                # Retry rate
                r5 = await db.execute(text(f"""
                    SELECT
                        COUNT(*) AS total_retries,
                        AVG(attempt_number) AS avg_attempts,
                        SUM(CASE WHEN NOT succeeded THEN 1 ELSE 0 END) AS failed_retries
                    FROM execution_retries
                    WHERE {time_filter}
                """))
                retries = dict(r5.mappings().fetchone() or {})

                # Broker health avg
                r6 = await db.execute(text(f"""
                    SELECT AVG(health_score) AS avg_health_score
                    FROM broker_health_history
                    WHERE {time_filter}
                """))
                health = dict(r6.mappings().fetchone() or {})

            return {
                "window": window,
                "speed": _clean(speed),
                "slippage": _clean(slippage),
                "fill_quality": _clean(quality),
                "rejections": _clean(rejections),
                "retries": _clean(retries),
                "broker_health": _clean(health),
            }
        except Exception as exc:
            _log.debug("execution_historical.get_window_stats_failed window=%s: %s", window, exc)
            return {"window": window, "error": str(exc)}

    async def get_all_windows(self) -> dict[str, Any]:
        """Return stats for all windows (1d, 7d, 30d, 90d, lifetime)."""
        results = {}
        for window in _WINDOWS:
            results[window] = await self.get_window_stats(window)
        return results

    async def get_trend(self, metric: str = "avg_exec_ms", days: int = 7) -> list[dict[str, Any]]:
        """Return daily trend for a latency or slippage metric."""
        try:
            col_map = {
                "avg_exec_ms":         ("execution_events",   "AVG(total_execution_ms)",    "signal_generated_at"),
                "avg_entry_slip_pct":  ("execution_slippage", "AVG(entry_slippage_pct)",    "recorded_at"),
                "avg_quality_score":   ("execution_metrics",  "AVG(execution_quality_score)", "recorded_at"),
            }
            if metric not in col_map:
                return []
            table, agg, ts_col = col_map[metric]
            async with self._sf() as db:
                r = await db.execute(text(f"""
                    SELECT DATE_TRUNC('day', {ts_col}) AS day,
                           {agg} AS value,
                           COUNT(*) AS n
                    FROM {table}
                    WHERE {ts_col} > NOW() - :days * INTERVAL '1 day'
                    GROUP BY DATE_TRUNC('day', {ts_col})
                    ORDER BY day
                """), {"days": days})  # noqa: S608
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.debug("execution_historical.get_trend_failed: %s", exc)
            return []


def _clean(d: dict) -> dict:
    return {k: (round(float(v), 4) if v is not None else None) for k, v in d.items()}
