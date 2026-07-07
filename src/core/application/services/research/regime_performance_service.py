"""RegimePerformanceService — win rate breakdown by regime × direction.

Reads signal_analytics to aggregate win rate, avg score, and sample size
per (regime, direction, strategy_type) grouping. Read-only.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


class ResearchRegimePerformanceService:
    """Computes and persists regime × direction performance breakdown."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute(self, lookback_days: int = 90, version_id: str | None = None) -> None:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            regime,
                            direction,
                            strategy_type,
                            COUNT(*) AS sample_size,
                            AVG(CASE WHEN outcome = 'WIN' THEN 1.0 ELSE 0.0 END) * 100 AS win_rate,
                            AVG(COALESCE(adjusted_score, raw_score)) AS avg_score,
                            AVG(CASE WHEN outcome = 'WIN' THEN COALESCE(mfe_pct, 0)
                                     ELSE -ABS(COALESCE(mae_pct, 0)) END) AS avg_pnl
                        FROM signal_analytics
                        WHERE created_at > NOW() - :days * INTERVAL '1 day'
                          AND outcome IN ('WIN', 'LOSS')
                          AND regime IS NOT NULL
                          AND direction IS NOT NULL
                        GROUP BY regime, direction, strategy_type
                        HAVING COUNT(*) >= 3
                        ORDER BY regime, direction
                    """),
                    {"days": lookback_days},
                )
                rows = r.fetchall()

                for row in rows:
                    await db.execute(
                        text("""
                            INSERT INTO research_regime_performance
                                (version_id, regime, direction, strategy_type,
                                 win_rate, avg_score, avg_pnl, sample_size,
                                 lookback_days, computed_at)
                            VALUES
                                (:vid, :regime, :dir, :st,
                                 :wr, :avg_score, :avg_pnl, :cnt,
                                 :days, NOW())
                        """),
                        {
                            "vid": version_id,
                            "regime": row[0], "dir": row[1], "st": row[2],
                            "cnt": row[3],
                            "wr": round(float(row[4]), 2) if row[4] else None,
                            "avg_score": round(float(row[5]), 2) if row[5] else None,
                            "avg_pnl": round(float(row[6]), 4) if row[6] else None,
                            "days": lookback_days,
                        },
                    )
                await db.commit()
            _log.info("research_regime_performance.computed rows=%d", len(rows))
        except Exception as exc:
            _log.warning("research_regime_performance.compute_failed: %s", exc)

    async def get_regime_breakdown(
        self, version_id: str | None = None, lookback_days: int = 90
    ) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT regime, direction, strategy_type,
                               win_rate, avg_score, avg_pnl, sample_size,
                               computed_at
                        FROM research_regime_performance
                        WHERE lookback_days = :days
                          AND (:vid IS NULL OR version_id = :vid)
                        ORDER BY computed_at DESC, win_rate DESC NULLS LAST
                        LIMIT 500
                    """),
                    {"days": lookback_days, "vid": version_id},
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("research_regime_performance.get_failed: %s", exc)
            return []
