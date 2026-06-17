"""SignalLeaderboardService — symbol, sector, and regime leaderboards.

Ranks symbols/sectors/regimes by win rate and profit factor using signal_analytics
outcome data. Runs without requiring any executed trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


@dataclass
class LeaderboardEntry:
    rank: int
    name: str           # ticker / sector / regime
    signal_count: int
    win_count: int
    win_rate: float
    profit_factor: float
    avg_return_pct: float
    expectancy: float


@dataclass
class SignalLeaderboard:
    computed_at: datetime
    lookback_days: int
    symbols: list[LeaderboardEntry]
    sectors: list[LeaderboardEntry]
    regimes: list[LeaderboardEntry]


class SignalLeaderboardService:
    """Computes symbol, sector, and regime leaderboards from signal outcome data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_leaderboard(self, lookback_days: int = 30) -> SignalLeaderboard:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        async with self._sf() as db:
            symbols = await self._query_leaderboard(db, "ticker", cutoff)
            sectors = await self._query_leaderboard(db, "COALESCE(sector, 'Unknown')", cutoff)
            regimes = await self._query_leaderboard(db, "regime", cutoff)

        return SignalLeaderboard(
            computed_at=datetime.now(UTC),
            lookback_days=lookback_days,
            symbols=_rank_entries(symbols, limit=20),
            sectors=_rank_entries(sectors, limit=15),
            regimes=_rank_entries(regimes, limit=10),
        )

    async def _query_leaderboard(
        self,
        db: AsyncSession,
        group_expr: str,
        cutoff: datetime,
    ) -> list[dict]:
        result = await db.execute(
            text(f"""
                SELECT
                    {group_expr} AS name,
                    COUNT(*) AS signal_count,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS win_count,
                    SUM(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN 1 ELSE 0 END) AS settled,
                    AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN return_1d_pct END) AS avg_return,
                    AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN mfe_pct END) AS avg_mfe,
                    AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN mae_pct END) AS avg_mae
                FROM signal_analytics
                WHERE was_accepted = true
                  AND outcome IS NOT NULL
                  AND outcome != 'OPEN'
                  AND created_at >= :cutoff
                GROUP BY {group_expr}
                HAVING COUNT(*) >= 3
                ORDER BY win_count DESC
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        return [dict(r._mapping) for r in rows]


def _rank_entries(rows: list[dict], limit: int) -> list[LeaderboardEntry]:
    entries: list[LeaderboardEntry] = []
    for row in rows:
        settled = int(row.get("settled") or 0)
        wins = int(row.get("win_count") or 0)
        avg_mfe = float(row.get("avg_mfe") or 0)
        avg_mae = float(row.get("avg_mae") or 0)

        win_rate = round(wins / settled * 100, 1) if settled > 0 else 0.0
        profit_factor = round(avg_mfe / avg_mae, 2) if avg_mae > 0 else 0.0
        avg_return = round(float(row.get("avg_return") or 0), 4)
        expectancy = round(
            (win_rate / 100 * avg_mfe) - ((1 - win_rate / 100) * avg_mae), 4
        )
        entries.append(LeaderboardEntry(
            rank=0,
            name=str(row["name"]),
            signal_count=int(row.get("signal_count") or 0),
            win_count=wins,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_return_pct=avg_return,
            expectancy=expectancy,
        ))

    # Sort by expectancy descending and assign rank
    entries.sort(key=lambda e: e.expectancy, reverse=True)
    for i, entry in enumerate(entries[:limit]):
        entry.rank = i + 1
    return entries[:limit]
