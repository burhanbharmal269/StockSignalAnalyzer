"""OptimizationInsightsService — rule-based text recommendations from signal analytics.

Generates human-readable insights without AI calls. Examples:
  "DIRECTIONAL works best in TRENDING regimes (win rate 72%)"
  "ADX filter is too strict — pass rate only 8%, consider lowering threshold"
  "BANKNIFTY has the highest expectancy of any symbol over 30 days"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


@dataclass
class Insight:
    priority: str       # HIGH | MEDIUM | LOW
    category: str       # STRATEGY | FILTER | SYMBOL | REGIME
    title: str
    description: str
    metric_value: float | None = None
    metric_label: str | None = None


@dataclass
class OptimizationReport:
    computed_at: datetime
    lookback_days: int
    insights: list[Insight]


class OptimizationInsightsService:
    """Generates rule-based optimization insights from signal_analytics data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_insights(self, lookback_days: int = 30) -> OptimizationReport:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        insights: list[Insight] = []

        async with self._sf() as db:
            insights.extend(await self._strategy_regime_insights(db, cutoff))
            insights.extend(await self._filter_insights(db, cutoff))
            insights.extend(await self._symbol_insights(db, cutoff))
            insights.extend(await self._volume_insights(db, cutoff))
            insights.extend(await self._regime_coverage_insights(db, cutoff))

        # Sort: HIGH first, then MEDIUM, then LOW
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        insights.sort(key=lambda x: priority_order.get(x.priority, 3))

        return OptimizationReport(
            computed_at=datetime.now(UTC),
            lookback_days=lookback_days,
            insights=insights[:20],
        )

    async def _strategy_regime_insights(self, db: AsyncSession, cutoff: datetime) -> list[Insight]:
        result = await db.execute(
            text("""
                SELECT regime, strategy_type,
                       COUNT(*) AS n,
                       SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN 1 ELSE 0 END) AS settled
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL AND outcome != 'OPEN'
                  AND created_at >= :cutoff
                GROUP BY regime, strategy_type
                HAVING COUNT(*) >= 5
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        insights = []
        for row in rows:
            settled = int(row.settled or 0)
            if settled == 0:
                continue
            win_rate = int(row.wins or 0) / settled * 100

            if win_rate >= 65:
                insights.append(Insight(
                    priority="HIGH",
                    category="STRATEGY",
                    title=f"{row.strategy_type} excels in {row.regime}",
                    description=(
                        f"{row.strategy_type} achieves {win_rate:.0f}% win rate in "
                        f"{row.regime} regime ({settled} signals). Prioritise this combination."
                    ),
                    metric_value=round(win_rate, 1),
                    metric_label="Win Rate %",
                ))
            elif win_rate <= 35 and settled >= 8:
                insights.append(Insight(
                    priority="MEDIUM",
                    category="STRATEGY",
                    title=f"Avoid {row.strategy_type} in {row.regime}",
                    description=(
                        f"{row.strategy_type} only achieves {win_rate:.0f}% win rate in "
                        f"{row.regime} regime ({settled} signals). Consider excluding."
                    ),
                    metric_value=round(win_rate, 1),
                    metric_label="Win Rate %",
                ))
        return insights

    async def _filter_insights(self, db: AsyncSession, cutoff: datetime) -> list[Insight]:
        result = await db.execute(
            text("""
                SELECT
                    rejection_reason,
                    COUNT(*) AS rejected_count,
                    (SELECT COUNT(*) FROM signal_analytics sa2
                     WHERE sa2.created_at >= :cutoff) AS total
                FROM signal_analytics
                WHERE was_accepted = false AND rejection_reason IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY rejection_reason
                ORDER BY rejected_count DESC
                LIMIT 10
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        insights = []
        for row in rows:
            total = int(row.total or 1)
            rejected = int(row.rejected_count or 0)
            rejection_rate = rejected / total * 100
            if rejection_rate >= 15:
                reason = str(row.rejection_reason).replace("_", " ").title()
                insights.append(Insight(
                    priority="MEDIUM",
                    category="FILTER",
                    title=f"{reason} is rejecting many signals",
                    description=(
                        f"'{reason}' filter rejected {rejected} signals "
                        f"({rejection_rate:.1f}% of all signals over {cutoff.strftime('%d days')}). "
                        f"Review threshold — may be too strict."
                    ),
                    metric_value=round(rejection_rate, 1),
                    metric_label="Rejection Rate %",
                ))
        return insights

    async def _symbol_insights(self, db: AsyncSession, cutoff: datetime) -> list[Insight]:
        result = await db.execute(
            text("""
                SELECT ticker,
                       COUNT(*) AS n,
                       SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN 1 ELSE 0 END) AS settled,
                       AVG(mfe_pct) AS avg_mfe,
                       AVG(mae_pct) AS avg_mae
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL AND outcome != 'OPEN'
                  AND created_at >= :cutoff
                GROUP BY ticker
                HAVING COUNT(*) >= 5
                ORDER BY wins DESC
                LIMIT 30
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        insights = []
        for row in rows:
            settled = int(row.settled or 0)
            if settled == 0:
                continue
            win_rate = int(row.wins or 0) / settled * 100
            avg_mfe = float(row.avg_mfe or 0)
            avg_mae = float(row.avg_mae or 0.001)
            pf = avg_mfe / avg_mae

            if win_rate >= 70 and pf >= 1.5:
                insights.append(Insight(
                    priority="HIGH",
                    category="SYMBOL",
                    title=f"{row.ticker} is a high-performance signal source",
                    description=(
                        f"{row.ticker} has {win_rate:.0f}% win rate and {pf:.1f}x profit factor "
                        f"across {settled} settled signals. Increase coverage weight."
                    ),
                    metric_value=round(win_rate, 1),
                    metric_label="Win Rate %",
                ))
        return insights[:3]

    async def _volume_insights(self, db: AsyncSession, cutoff: datetime) -> list[Insight]:
        result = await db.execute(
            text("""
                SELECT
                    CASE WHEN volume_ratio_at_signal >= 2.0 THEN 'HIGH_VOLUME'
                         WHEN volume_ratio_at_signal >= 1.2 THEN 'NORMAL_VOLUME'
                         ELSE 'LOW_VOLUME' END AS vol_bucket,
                    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED') THEN 1 ELSE 0 END) AS settled
                FROM signal_analytics
                WHERE was_accepted = true AND outcome IS NOT NULL AND outcome != 'OPEN'
                  AND volume_ratio_at_signal IS NOT NULL
                  AND created_at >= :cutoff
                GROUP BY vol_bucket
                HAVING COUNT(*) >= 5
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        insights = []
        bucket_stats = {row.vol_bucket: row for row in rows}

        high = bucket_stats.get("HIGH_VOLUME")
        low = bucket_stats.get("LOW_VOLUME")
        if high and low:
            h_settled = int(high.settled or 1)
            l_settled = int(low.settled or 1)
            h_wr = int(high.wins or 0) / h_settled * 100
            l_wr = int(low.wins or 0) / l_settled * 100
            if h_wr - l_wr >= 15:
                insights.append(Insight(
                    priority="MEDIUM",
                    category="FILTER",
                    title="High-volume signals outperform low-volume",
                    description=(
                        f"Signals with volume ratio ≥ 2.0 have {h_wr:.0f}% win rate vs "
                        f"{l_wr:.0f}% for low-volume signals. Consider raising minimum volume threshold."
                    ),
                    metric_value=round(h_wr - l_wr, 1),
                    metric_label="Win Rate Delta %",
                ))
        return insights

    async def _regime_coverage_insights(self, db: AsyncSession, cutoff: datetime) -> list[Insight]:
        result = await db.execute(
            text("""
                SELECT regime, COUNT(*) AS n
                FROM signal_analytics
                WHERE was_accepted = true AND created_at >= :cutoff
                GROUP BY regime
                ORDER BY n DESC
            """),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()
        insights = []
        total = sum(int(r.n) for r in rows)
        if total == 0:
            return []

        for row in rows:
            share = int(row.n) / total * 100
            if share <= 5:
                insights.append(Insight(
                    priority="LOW",
                    category="REGIME",
                    title=f"Low signal coverage in {row.regime} regime",
                    description=(
                        f"Only {int(row.n)} signals ({share:.1f}%) generated in {row.regime} regime. "
                        f"Strategy coverage may be insufficient for this market condition."
                    ),
                    metric_value=round(share, 1),
                    metric_label="Coverage %",
                ))
        return insights[:2]
