"""CalibrationService — weekly confidence calibration runner.

Queries signal_performance_stats, groups by confidence bucket, and
computes calibration factors. Writes factors to Redis so the Confidence
Engine can apply them at score time.

Run schedule: every Sunday at 05:00 IST (orchestrated externally).
Reference: docs/21_SIGNAL_ENGINE.md §Confidence Calibration
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.infrastructure.database.models.signal_performance_models import (
    SignalPerformanceStatsOrm,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.infrastructure.config.confidence_config import ConfidenceConfig

_log = logging.getLogger(__name__)

_CALIBRATION_KEY_PREFIX  = "confidence:calibration"
_CALIBRATION_LAST_RUN_KEY = "confidence:calibration:last_run_count"

# All regime values (must match MarketRegime enum string values)
_ALL_REGIMES = [
    "TRENDING_BULLISH",
    "TRENDING_BEARISH",
    "SIDEWAYS",
    "HIGH_VOLATILITY",
    "LOW_VOLATILITY",
]


class CalibrationService:
    """Computes and stores weekly confidence calibration factors."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        config: ConfidenceConfig,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._cfg = config.calibration
        self._gate_min = config.gate.min_confidence
        self._error_threshold = config.calibration.error_threshold_pct

    async def run_calibration(self) -> dict[str, float]:
        """Compute calibration factors for all confidence buckets.

        Returns a dict of bucket_label → calibration_factor.
        Factors are also written to Redis for real-time consumption.
        """
        cutoff = datetime.now(UTC) - timedelta(days=self._cfg.lookback_days)
        factors: dict[str, float] = {}

        for lo, hi in self._buckets():
            label = f"{lo}-{hi}"
            factor = await self._compute_bucket_factor(lo, hi, cutoff)
            factors[label] = factor
            key = f"{_CALIBRATION_KEY_PREFIX}:{label}"
            await self._redis.set(key, str(factor))
            _log.info(
                "calibration bucket=%s factor=%.4f written to Redis key=%s",
                label,
                factor,
                key,
            )

        _log.info("calibration complete: %d buckets updated", len(factors))
        return factors

    async def _compute_bucket_factor(
        self, lo: float, hi: float, cutoff: datetime
    ) -> float:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        func.cast(
                            SignalPerformanceStatsOrm.outcome == "WIN", type_=None
                        )
                    ).label("wins"),
                ).where(
                    and_(
                        SignalPerformanceStatsOrm.confidence >= lo,
                        SignalPerformanceStatsOrm.confidence <= hi,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
            )
            row = result.one()
            total: int = row.total or 0
            wins: int = row.wins or 0

        if total < self._cfg.min_bucket_size:
            _log.debug("calibration bucket=%d-%d skipped: only %d samples", lo, hi, total)
            return 1.0

        midpoint = (lo + hi) / 2.0
        actual_win_rate = (wins / total) * 100.0
        predicted_win_rate = midpoint
        error = abs(predicted_win_rate - actual_win_rate)

        if error <= self._error_threshold:
            return 1.0

        factor = actual_win_rate / predicted_win_rate if predicted_win_rate > 0.0 else 1.0
        _log.warning(
            "calibration bucket=%d-%d error=%.1f%% factor=%.4f",
            lo,
            hi,
            error,
            factor,
        )
        return factor

    async def run_regime_calibration(self) -> dict[str, dict[str, float]]:
        """Compute calibration factors grouped by regime AND confidence bucket.

        Regime-specific factors let the Confidence Engine apply a tighter
        correction for regimes where the model is systematically wrong (e.g.,
        HIGH_VOLATILITY signals are over-confident vs TRENDING where they are
        well-calibrated).

        Redis keys: ``confidence:calibration:{regime}:{lo}-{hi}``
        Returns nested dict: {regime: {bucket_label: factor}}.
        """
        cutoff = datetime.now(UTC) - timedelta(days=self._cfg.lookback_days)
        all_factors: dict[str, dict[str, float]] = {}

        for regime in _ALL_REGIMES:
            regime_factors: dict[str, float] = {}
            for lo, hi in self._buckets():
                label  = f"{lo}-{hi}"
                factor = await self._compute_regime_bucket_factor(regime, lo, hi, cutoff)
                regime_factors[label] = factor
                key = f"{_CALIBRATION_KEY_PREFIX}:{regime}:{label}"
                await self._redis.set(key, str(factor))
                _log.debug(
                    "calibration regime=%s bucket=%s factor=%.4f key=%s",
                    regime, label, factor, key,
                )
            all_factors[regime] = regime_factors
            _log.info("calibration.regime_done regime=%s buckets=%d", regime, len(regime_factors))

        return all_factors

    async def _compute_regime_bucket_factor(
        self, regime: str, lo: float, hi: float, cutoff: datetime
    ) -> float:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    func.count().label("total"),
                    func.sum(
                        func.cast(
                            SignalPerformanceStatsOrm.outcome == "WIN", type_=None
                        )
                    ).label("wins"),
                ).where(
                    and_(
                        SignalPerformanceStatsOrm.regime_at_signal == regime,
                        SignalPerformanceStatsOrm.confidence >= lo,
                        SignalPerformanceStatsOrm.confidence <= hi,
                        SignalPerformanceStatsOrm.recorded_at >= cutoff,
                    )
                )
            )
            row   = result.one()
            total = row.total or 0
            wins  = row.wins  or 0

        if total < self._cfg.min_bucket_size:
            return 1.0

        midpoint        = (lo + hi) / 2.0
        actual_win_rate = (wins / total) * 100.0
        error           = abs(midpoint - actual_win_rate)
        if error <= self._error_threshold:
            return 1.0

        factor = actual_win_rate / midpoint if midpoint > 0.0 else 1.0
        _log.warning(
            "calibration regime=%s bucket=%d-%d error=%.1f%% factor=%.4f",
            regime, lo, hi, error, factor,
        )
        return factor

    async def run_if_new_outcomes(self, min_new_outcomes: int = 20) -> dict | None:
        """Run calibration only when at least ``min_new_outcomes`` new signals
        have been recorded since the last run.

        Intended for daily cron invocation — avoids stale recalibration when
        few signals were generated (weekend, holiday, kill-switch active).

        Returns the calibration result dict or None when skipped.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count()).where(
                    SignalPerformanceStatsOrm.recorded_at
                    >= datetime.now(UTC) - timedelta(days=self._cfg.lookback_days)
                )
            )
            current_count: int = result.scalar_one() or 0

        last_str = await self._redis.get(_CALIBRATION_LAST_RUN_KEY)
        last_count = int(last_str) if last_str else 0

        new_outcomes = current_count - last_count
        if new_outcomes < min_new_outcomes:
            _log.info(
                "calibration.skipped new_outcomes=%d threshold=%d",
                new_outcomes, min_new_outcomes,
            )
            return None

        _log.info("calibration.triggered new_outcomes=%d", new_outcomes)
        base_factors   = await self.run_calibration()
        regime_factors = await self.run_regime_calibration()
        await self._redis.set(_CALIBRATION_LAST_RUN_KEY, str(current_count))
        return {"base": base_factors, "regime": regime_factors}

    @staticmethod
    def _buckets() -> list[tuple[int, int]]:
        return [(65, 69), (70, 74), (75, 79), (80, 84), (85, 89), (90, 100)]
