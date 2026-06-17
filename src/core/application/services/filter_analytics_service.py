"""FilterAnalyticsService — audits filter effectiveness.

Analyses signal_analytics to determine how each filter affects signal quality:

Filters tracked:
  - Volume Filter (vol_ratio threshold)
  - ADX Filter (adx_gate threshold)
  - Score Gate (min_score)
  - Confidence Gate (min_confidence)
  - Risk Filter (risk engine rejection)
  - Dedup Filter (duplicate rejection)

For each filter, computes:
  - Signals evaluated (before filter)
  - Signals passing (after filter)
  - Pass rate %
  - Win rate of signals that passed vs all signals
  - Whether the filter is improving or hurting performance
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)


@dataclass
class FilterMetrics:
    filter_name: str
    description: str
    signals_before: int
    signals_after: int
    pass_rate_pct: float
    rejected_count: int
    win_rate_passed: float   # win rate of signals that passed this filter
    win_rate_rejected: float # win rate of signals that were rejected (if tracked)
    # positive = filter helps (passed signals have higher win rate)
    # negative = filter hurts (passed signals have lower win rate than rejected)
    performance_delta: float
    verdict: str             # "IMPROVING" | "HURTING" | "NEUTRAL" | "INSUFFICIENT_DATA"


@dataclass
class FilterAnalyticsReport:
    computed_at: datetime
    lookback_days: int
    filters: list[FilterMetrics] = field(default_factory=list)
    total_signals_evaluated: int = 0
    total_signals_accepted: int  = 0

    @property
    def improving_filters(self) -> list[FilterMetrics]:
        return [f for f in self.filters if f.verdict == "IMPROVING"]

    @property
    def hurting_filters(self) -> list[FilterMetrics]:
        return [f for f in self.filters if f.verdict == "HURTING"]


class FilterAnalyticsService:
    """Computes filter effectiveness from signal_analytics data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_report(self, lookback_days: int = 30) -> FilterAnalyticsReport:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        filters = await self._compute_filters(cutoff)

        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS accepted
                    FROM signal_analytics WHERE created_at >= :cutoff
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
            total    = int(row.total    or 0)
            accepted = int(row.accepted or 0)

        return FilterAnalyticsReport(
            computed_at=datetime.now(UTC),
            lookback_days=lookback_days,
            filters=filters,
            total_signals_evaluated=total,
            total_signals_accepted=accepted,
        )

    async def _compute_filters(self, cutoff: datetime) -> list[FilterMetrics]:
        filters: list[FilterMetrics] = []
        filters.append(await self._score_gate_filter(cutoff))
        filters.append(await self._confidence_gate_filter(cutoff))
        filters.append(await self._volume_filter(cutoff))
        filters.append(await self._adx_filter(cutoff))
        filters.append(await self._risk_filter(cutoff))
        return [f for f in filters if f is not None]

    async def _score_gate_filter(self, cutoff: datetime) -> FilterMetrics:
        """Score gate: signals that passed vs were weak-rejected."""
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN rejection_reason != 'WEAK_SIGNAL' OR was_accepted THEN 1 ELSE 0 END) AS passed,
                        SUM(CASE WHEN rejection_reason = 'WEAK_SIGNAL' THEN 1 ELSE 0 END) AS score_rejected,
                        AVG(CASE WHEN outcome IN ('WIN','LOSS') AND was_accepted
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_passed,
                        AVG(CASE WHEN outcome IN ('WIN','LOSS') AND rejection_reason = 'WEAK_SIGNAL'
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_rejected
                    FROM signal_analytics WHERE created_at >= :cutoff
                      AND rejection_reason IS NOT NULL OR was_accepted
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
        return self._build_metric(
            row, "Score Gate", "min_score threshold rejects low-quality signals",
        )

    async def _confidence_gate_filter(self, cutoff: datetime) -> FilterMetrics:
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN was_accepted OR rejection_reason = 'RISK_REJECTED' THEN 1 ELSE 0 END) AS passed,
                        SUM(CASE WHEN rejection_reason = 'WEAK_SIGNAL' AND confidence < 25 THEN 1 ELSE 0 END) AS score_rejected,
                        AVG(CASE WHEN was_accepted AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_passed,
                        0.0 AS win_rate_rejected
                    FROM signal_analytics WHERE created_at >= :cutoff
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
        return self._build_metric(
            row, "Confidence Gate", "min_confidence threshold — filters low-certainty signals",
        )

    async def _volume_filter(self, cutoff: datetime) -> FilterMetrics:
        """Volume filter impact: signals with vol_ratio > 1.2 vs < 1.2."""
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN volume_ratio_at_signal >= 1.2 THEN 1 ELSE 0 END) AS passed,
                        SUM(CASE WHEN volume_ratio_at_signal < 1.2 THEN 1 ELSE 0 END) AS score_rejected,
                        AVG(CASE WHEN volume_ratio_at_signal >= 1.2 AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_passed,
                        AVG(CASE WHEN volume_ratio_at_signal < 1.2 AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_rejected
                    FROM signal_analytics WHERE created_at >= :cutoff AND volume_ratio_at_signal IS NOT NULL
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
        return self._build_metric(
            row, "Volume Filter", "vol_ratio ≥ 1.2 selects stocks with expanding volume",
        )

    async def _adx_filter(self, cutoff: datetime) -> FilterMetrics:
        """ADX filter: signals where ADX > 15 vs ADX ≤ 15."""
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN adx_at_signal >= 15 THEN 1 ELSE 0 END) AS passed,
                        SUM(CASE WHEN adx_at_signal < 15 THEN 1 ELSE 0 END) AS score_rejected,
                        AVG(CASE WHEN adx_at_signal >= 15 AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_passed,
                        AVG(CASE WHEN adx_at_signal < 15 AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_rejected
                    FROM signal_analytics WHERE created_at >= :cutoff AND adx_at_signal IS NOT NULL
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
        return self._build_metric(
            row, "ADX Filter", "adx_gate ≥ 15 requires minimum trend strength",
        )

    async def _risk_filter(self, cutoff: datetime) -> FilterMetrics:
        """Risk engine: signals that passed risk vs were risk-rejected."""
        async with self._sf() as db:
            r = await db.execute(
                text("""
                    SELECT
                        SUM(CASE WHEN was_accepted OR rejection_reason = 'RISK_REJECTED' THEN 1 ELSE 0 END) AS total,
                        SUM(CASE WHEN was_accepted THEN 1 ELSE 0 END) AS passed,
                        SUM(CASE WHEN rejection_reason = 'RISK_REJECTED' THEN 1 ELSE 0 END) AS score_rejected,
                        AVG(CASE WHEN was_accepted AND outcome IN ('WIN','LOSS')
                            THEN (CASE WHEN outcome='WIN' THEN 1.0 ELSE 0.0 END) END) AS win_rate_passed,
                        0.0 AS win_rate_rejected
                    FROM signal_analytics WHERE created_at >= :cutoff
                """),
                {"cutoff": cutoff},
            )
            row = r.fetchone()
        return self._build_metric(
            row, "Risk Filter", "Risk engine 15-check pre-trade validation",
        )

    @staticmethod
    def _build_metric(row, name: str, description: str) -> FilterMetrics:
        total    = int(row.total or 0)
        passed   = int(row.passed or 0)
        rejected = int(row.score_rejected or 0)
        wr_pass  = round(float(row.win_rate_passed or 0) * 100, 1)
        wr_rej   = round(float(row.win_rate_rejected or 0) * 100, 1) if row.win_rate_rejected else 0.0
        pass_rate = round(passed / max(total, 1) * 100, 1)
        delta    = wr_pass - wr_rej

        if total < 10:
            verdict = "INSUFFICIENT_DATA"
        elif delta > 5:
            verdict = "IMPROVING"
        elif delta < -5:
            verdict = "HURTING"
        else:
            verdict = "NEUTRAL"

        return FilterMetrics(
            filter_name=name,
            description=description,
            signals_before=total,
            signals_after=passed,
            pass_rate_pct=pass_rate,
            rejected_count=rejected,
            win_rate_passed=wr_pass,
            win_rate_rejected=wr_rej,
            performance_delta=round(delta, 1),
            verdict=verdict,
        )
