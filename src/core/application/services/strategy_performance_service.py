"""StrategyPerformanceService — continuously evaluates every strategy.

Queries signal_analytics to compute per-strategy metrics:
  - Signal count / win rate / profit factor
  - Average return / Sharpe ratio / max drawdown
  - Expectancy / average holding time
  - Leaderboard ranking

Called by the analytics API endpoints and updated in background every hour.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


@dataclass
class StrategyMetrics:
    strategy_type: str
    signal_count: int
    accepted_count: int
    win_count: int
    loss_count: int
    open_count: int

    win_rate: float             # 0–100 %
    profit_factor: float        # gross_wins / gross_losses
    avg_return_pct: float       # average return for closed signals
    sharpe_ratio: float         # annualised return / std_dev
    max_drawdown_pct: float
    expectancy: float           # win_rate × avg_win - loss_rate × avg_loss
    avg_holding_time_minutes: float

    # Score quality indicators
    avg_score: float
    avg_confidence: float

    # Component contributions (average across accepted signals)
    avg_trend_score: float
    avg_volume_score: float
    avg_vwap_score: float
    avg_oi_score: float
    avg_sentiment_score: float

    rank: int = 0


@dataclass
class StrategyLeaderboard:
    computed_at: datetime
    lookback_days: int
    strategies: list[StrategyMetrics] = field(default_factory=list)

    @property
    def best_strategy(self) -> StrategyMetrics | None:
        return self.strategies[0] if self.strategies else None

    @property
    def worst_strategy(self) -> StrategyMetrics | None:
        return self.strategies[-1] if len(self.strategies) > 1 else None


class StrategyPerformanceService:
    """Computes strategy performance leaderboard from signal_analytics."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_leaderboard(self, lookback_days: int = 30) -> StrategyLeaderboard:
        """Compute strategy performance leaderboard for the last `lookback_days`."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        metrics_list = await self._fetch_strategy_metrics(cutoff)

        # Rank by expectancy (best to worst)
        metrics_list.sort(key=lambda m: m.expectancy, reverse=True)
        for i, m in enumerate(metrics_list, start=1):
            m.rank = i

        return StrategyLeaderboard(
            computed_at=datetime.now(UTC),
            lookback_days=lookback_days,
            strategies=metrics_list,
        )

    async def _fetch_strategy_metrics(self, cutoff: datetime) -> list[StrategyMetrics]:
        async with self._sf() as db:
            # Per-strategy aggregated stats
            result = await db.execute(
                text("""
                    SELECT
                        strategy_type,
                        COUNT(*) AS signal_count,
                        SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted_count,
                        SUM(CASE WHEN outcome = 'WIN'  THEN 1 ELSE 0 END) AS win_count,
                        SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS loss_count,
                        SUM(CASE WHEN outcome = 'OPEN' THEN 1 ELSE 0 END) AS open_count,

                        -- Returns for closed signals
                        AVG(CASE WHEN outcome IN ('WIN','LOSS') THEN return_1d_pct END) AS avg_return,
                        AVG(CASE WHEN outcome = 'WIN'  THEN return_1d_pct END) AS avg_win,
                        AVG(CASE WHEN outcome = 'LOSS' THEN return_1d_pct END) AS avg_loss,
                        SUM(CASE WHEN outcome = 'WIN'  THEN GREATEST(return_1d_pct, 0) END) AS gross_win,
                        SUM(CASE WHEN outcome = 'LOSS' THEN ABS(LEAST(return_1d_pct, 0)) END) AS gross_loss,

                        -- MFE/MAE
                        AVG(mfe_pct) AS avg_mfe,
                        AVG(mae_pct) AS avg_mae,

                        -- Holding time (use time_to_target when WIN, time_to_stop when LOSS)
                        AVG(CASE
                            WHEN outcome = 'WIN'  THEN time_to_target_minutes
                            WHEN outcome = 'LOSS' THEN time_to_stop_minutes
                        END) AS avg_hold_mins,

                        -- Score quality
                        AVG(CASE WHEN was_accepted THEN adjusted_score END) AS avg_score,
                        AVG(CASE WHEN was_accepted THEN confidence END) AS avg_conf,

                        -- Component scores
                        AVG(CASE WHEN was_accepted THEN trend_score END) AS avg_trend,
                        AVG(CASE WHEN was_accepted THEN volume_score END) AS avg_vol,
                        AVG(CASE WHEN was_accepted THEN vwap_score END) AS avg_vwap,
                        AVG(CASE WHEN was_accepted THEN oi_score END) AS avg_oi,
                        AVG(CASE WHEN was_accepted THEN sentiment_score END) AS avg_sent,

                        -- Standard deviation for Sharpe
                        STDDEV(CASE WHEN outcome IN ('WIN','LOSS') THEN return_1d_pct END) AS stddev_return

                    FROM signal_analytics
                    WHERE created_at >= :cutoff
                    GROUP BY strategy_type
                    HAVING COUNT(*) >= 3
                    ORDER BY strategy_type
                """),
                {"cutoff": cutoff},
            )
            rows = result.fetchall()

        metrics: list[StrategyMetrics] = []
        for row in rows:
            win_rate    = _safe_pct(row.win_count, row.accepted_count)
            loss_rate   = 100.0 - win_rate
            avg_win     = float(row.avg_win or 0)
            avg_loss    = abs(float(row.avg_loss or 0))
            gross_win   = float(row.gross_win or 0)
            gross_loss  = float(row.gross_loss or 0.001)  # avoid div/0
            pf          = gross_win / gross_loss
            expectancy  = (win_rate / 100) * avg_win - (loss_rate / 100) * avg_loss
            std         = float(row.stddev_return or 1.0)
            avg_ret     = float(row.avg_return or 0)
            # Annualise: each signal ~1 day, 252 trading days
            sharpe      = (avg_ret / std) * math.sqrt(252) if std > 0 else 0.0
            max_dd      = float(row.avg_mae or 0)  # proxy: average MAE as drawdown

            metrics.append(StrategyMetrics(
                strategy_type=row.strategy_type,
                signal_count=int(row.signal_count),
                accepted_count=int(row.accepted_count or 0),
                win_count=int(row.win_count or 0),
                loss_count=int(row.loss_count or 0),
                open_count=int(row.open_count or 0),
                win_rate=round(win_rate, 1),
                profit_factor=round(pf, 2),
                avg_return_pct=round(avg_ret, 2),
                sharpe_ratio=round(sharpe, 2),
                max_drawdown_pct=round(max_dd, 2),
                expectancy=round(expectancy, 3),
                avg_holding_time_minutes=round(float(row.avg_hold_mins or 0), 0),
                avg_score=round(float(row.avg_score or 0), 1),
                avg_confidence=round(float(row.avg_conf or 0), 1),
                avg_trend_score=round(float(row.avg_trend or 0), 2),
                avg_volume_score=round(float(row.avg_vol or 0), 2),
                avg_vwap_score=round(float(row.avg_vwap or 0), 2),
                avg_oi_score=round(float(row.avg_oi or 0), 2),
                avg_sentiment_score=round(float(row.avg_sent or 0), 2),
            ))
        return metrics


def _safe_pct(numerator, denominator) -> float:
    n = int(numerator or 0)
    d = int(denominator or 0)
    return round(n / d * 100, 1) if d > 0 else 0.0
