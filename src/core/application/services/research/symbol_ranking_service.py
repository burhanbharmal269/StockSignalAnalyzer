"""SymbolRankingService — ranks tickers by composite signal performance.

Composite rank score = 0.4×win_rate + 0.3×avg_score_norm + 0.2×signal_count_norm + 0.1×avg_mfe
All values normalised to [0,1] before weighting. Read-only on signal_analytics.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return values
    mn, mx = min(values), max(values)
    rng = mx - mn
    if rng == 0:
        return [0.5] * len(values)
    return [(v - mn) / rng for v in values]


class SymbolRankingService:
    """Computes and persists per-ticker performance rankings."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_rankings(self, lookback_days: int = 90) -> None:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                            ticker,
                            COUNT(*) AS signal_count,
                            AVG(CASE WHEN outcome = 'WIN' THEN 1.0 ELSE 0.0 END) * 100 AS win_rate,
                            AVG(COALESCE(adjusted_score, raw_score)) AS avg_score,
                            AVG(CASE WHEN outcome = 'WIN' THEN COALESCE(mfe_pct, 0)
                                     ELSE -ABS(COALESCE(mae_pct, 0)) END) AS avg_pnl,
                            AVG(COALESCE(mfe_pct, 0)) AS avg_mfe
                        FROM signal_analytics
                        WHERE created_at > NOW() - :days * INTERVAL '1 day'
                          AND outcome IN ('WIN', 'LOSS')
                          AND ticker IS NOT NULL
                        GROUP BY ticker
                        HAVING COUNT(*) >= 3
                        ORDER BY ticker
                    """),
                    {"days": lookback_days},
                )
                rows = r.fetchall()

            if not rows:
                return

            tickers = [row[0] for row in rows]
            signal_counts = [float(row[1]) for row in rows]
            win_rates = [float(row[2] or 0) for row in rows]
            avg_scores = [float(row[3] or 0) for row in rows]
            avg_pnls = [float(row[4] or 0) for row in rows]
            avg_mfes = [float(row[5] or 0) for row in rows]

            norm_wr = _normalise(win_rates)
            norm_sc = _normalise(signal_counts)
            norm_as = _normalise(avg_scores)
            norm_mfe = _normalise(avg_mfes)

            composite = [
                0.4 * nwr + 0.3 * nas + 0.2 * nsc + 0.1 * nmfe
                for nwr, nas, nsc, nmfe in zip(norm_wr, norm_as, norm_sc, norm_mfe)
            ]

            ranked = sorted(
                enumerate(tickers), key=lambda x: composite[x[0]], reverse=True
            )

            async with self._sf() as db:
                for rank_pos, (idx, ticker) in enumerate(ranked, start=1):
                    await db.execute(
                        text("""
                            INSERT INTO research_symbol_rankings
                                (ticker, signal_count, win_rate, avg_score, avg_pnl,
                                 avg_mfe, composite_rank_score, rank, lookback_days, computed_at)
                            VALUES
                                (:ticker, :cnt, :wr, :as2, :pnl,
                                 :mfe, :comp, :rank, :days, NOW())
                        """),
                        {
                            "ticker": ticker,
                            "cnt": int(signal_counts[idx]),
                            "wr": round(win_rates[idx], 2),
                            "as2": round(avg_scores[idx], 2),
                            "pnl": round(avg_pnls[idx], 4),
                            "mfe": round(avg_mfes[idx], 4),
                            "comp": round(composite[idx], 4),
                            "rank": rank_pos,
                            "days": lookback_days,
                        },
                    )
                await db.commit()
            _log.info("symbol_ranking_service.computed tickers=%d", len(rows))
        except Exception as exc:
            _log.warning("symbol_ranking_service.compute_failed: %s", exc)

    async def get_rankings(self, limit: int = 50, lookback_days: int = 90) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT DISTINCT ON (ticker)
                            ticker, signal_count, win_rate, avg_score, avg_pnl,
                            avg_mfe, composite_rank_score, rank, computed_at
                        FROM research_symbol_rankings
                        WHERE lookback_days = :days
                        ORDER BY ticker, computed_at DESC
                    """),
                    {"days": lookback_days},
                )
                rows = sorted(
                    [dict(row) for row in r.mappings().fetchall()],
                    key=lambda x: x.get("rank") or 9999,
                )
                return rows[:limit]
        except Exception as exc:
            _log.warning("symbol_ranking_service.get_failed: %s", exc)
            return []
