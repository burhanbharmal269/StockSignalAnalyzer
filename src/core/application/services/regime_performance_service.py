"""RegimePerformanceService — win rate and profit factor per market regime × strategy.

Answers: "Which strategy works best in trending markets?" without requiring executed orders.
Queries signal_analytics outcome data grouped by (regime, strategy_type).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


@dataclass
class RegimeStrategyMetrics:
    regime: str
    strategy_type: str
    signal_count: int
    win_count: int
    loss_count: int
    partial_count: int
    win_rate: float
    profit_factor: float
    avg_return_pct: float
    expectancy: float


@dataclass
class RegimePerformanceReport:
    computed_at: datetime
    lookback_days: int
    regime_metrics: list[RegimeStrategyMetrics]
    best_per_regime: dict[str, str]  # regime → best strategy_type


class RegimePerformanceService:
    """Computes strategy performance cross-tabulated by market regime."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_report(self, lookback_days: int = 30) -> RegimePerformanceReport:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        async with self._sf() as db:
            result = await db.execute(
                text("""
                    SELECT
                        regime,
                        strategy_type,
                        COUNT(*) AS signal_count,
                        SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS win_count,
                        SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS loss_count,
                        SUM(CASE WHEN outcome = 'PARTIAL' THEN 1 ELSE 0 END) AS partial_count,
                        AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED')
                            THEN return_1d_pct END) AS avg_return,
                        AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED')
                            THEN mfe_pct END) AS avg_mfe,
                        AVG(CASE WHEN outcome IN ('WIN','LOSS','PARTIAL','EXPIRED')
                            THEN mae_pct END) AS avg_mae
                    FROM signal_analytics
                    WHERE was_accepted = true
                      AND outcome IS NOT NULL
                      AND outcome != 'OPEN'
                      AND created_at >= :cutoff
                    GROUP BY regime, strategy_type
                    HAVING COUNT(*) >= 3
                    ORDER BY regime, win_count DESC
                """),
                {"cutoff": cutoff},
            )
            rows = result.fetchall()

        metrics: list[RegimeStrategyMetrics] = []
        for row in rows:
            total = int(row.signal_count)
            wins = int(row.win_count or 0)
            losses = int(row.loss_count or 0)
            partials = int(row.partial_count or 0)
            settled = wins + losses + partials

            win_rate = round(wins / settled * 100, 1) if settled > 0 else 0.0
            avg_mfe = float(row.avg_mfe or 0)
            avg_mae = float(row.avg_mae or 0)
            profit_factor = round(avg_mfe / avg_mae, 2) if avg_mae > 0 else 0.0
            avg_return = round(float(row.avg_return or 0), 4)
            expectancy = round(
                (win_rate / 100 * avg_mfe) - ((1 - win_rate / 100) * avg_mae), 4
            )

            metrics.append(RegimeStrategyMetrics(
                regime=row.regime,
                strategy_type=row.strategy_type,
                signal_count=total,
                win_count=wins,
                loss_count=losses,
                partial_count=partials,
                win_rate=win_rate,
                profit_factor=profit_factor,
                avg_return_pct=avg_return,
                expectancy=expectancy,
            ))

        best_per_regime = _find_best_per_regime(metrics)

        return RegimePerformanceReport(
            computed_at=datetime.now(UTC),
            lookback_days=lookback_days,
            regime_metrics=metrics,
            best_per_regime=best_per_regime,
        )


def _find_best_per_regime(metrics: list[RegimeStrategyMetrics]) -> dict[str, str]:
    best: dict[str, RegimeStrategyMetrics] = {}
    for m in metrics:
        if m.regime not in best or m.expectancy > best[m.regime].expectancy:
            best[m.regime] = m
    return {regime: m.strategy_type for regime, m in best.items()}
