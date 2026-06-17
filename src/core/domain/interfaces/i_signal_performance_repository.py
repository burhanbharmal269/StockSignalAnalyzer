"""ISignalPerformanceRepository — domain interface for signal outcome storage.

Implementors query and persist signal_performance_stats records used by
the Confidence Engine for win-rate lookup, historical accuracy, and
loss-streak calculation.

Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md §signal_performance_stats
           docs/21_SIGNAL_ENGINE.md §Stage 3
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class KellySizingStats:
    """Aggregate stats needed for Kelly criterion position sizing.

    sample_count: total trades in the lookback window for this instrument/class
    win_count: trades with outcome == "WIN"
    loss_count: trades with outcome == "LOSS"
    win_rate: win_count / sample_count  (0.0–1.0)
    win_loss_ratio: avg_win_pnl_bps / avg_loss_pnl_bps (absolute);
                    None when no loss records exist (edge=fallback)
    """

    sample_count: int
    win_count: int
    loss_count: int
    win_rate: float
    win_loss_ratio: float | None


@dataclass(frozen=True)
class SignalPerformanceRecord:
    """Domain representation of a signal_performance_stats row.

    Populated by the outcome recorder (Phase 14+) once a position closes.
    Phase 12 reads existing records but does not write them during scoring.
    """

    fingerprint: str
    signal_id: str
    instrument: str
    instrument_class: str
    direction: str
    regime_at_signal: str
    score_bucket: str
    vix_bucket: str
    top_2_components: list[str]
    score: float
    confidence: float
    outcome: str                              # "WIN" | "LOSS" | "TIME_EXIT"
    entry_price: float
    exit_price: float
    pnl_bps: int
    hold_duration_minutes: int
    dte_at_signal: int
    confidence_calibration_error: float | None
    recorded_at: datetime


class ISignalPerformanceRepository(ABC):
    """Read/write interface for signal_performance_stats."""

    @abstractmethod
    async def get_win_rate(
        self,
        regime: str,
        direction: str,
        instrument_class: str,
        lookback_days: int,
        min_samples: int,
    ) -> float | None:
        """Return win rate (0.0–1.0) or None if < min_samples."""

    @abstractmethod
    async def get_historical_accuracy(
        self,
        fingerprint: str,
        min_samples: int,
        lookback_days: int,
    ) -> tuple[float, int] | None:
        """Return (accuracy 0.0–1.0, sample_count) or None if < min_samples.

        Only considers records within the most recent ``lookback_days`` window
        to prevent stale historical data from distorting accuracy after market
        structure changes.
        """

    @abstractmethod
    async def get_consecutive_losses(
        self,
        instrument: str,
        lookback_trading_days: int,
    ) -> int:
        """Return count of consecutive LOSS outcomes for instrument (most recent first)."""

    @abstractmethod
    async def get_recent_outcomes(self, instrument: str, limit: int) -> list[str]:
        """Return up to ``limit`` most recent outcome strings for instrument, most-recent first.

        Returns a list of ``"WIN"``, ``"LOSS"``, or ``"TIME_EXIT"`` strings.
        Used by the recent_performance_adj calculation in ConfidenceCalculator.
        """

    @abstractmethod
    async def get_sizing_stats(
        self,
        instrument: str,
        instrument_class: str,
        lookback_days: int,
        min_samples: int = 30,
    ) -> KellySizingStats | None:
        """Return Kelly sizing stats or None when total trades < min_samples.

        Queries all WIN and LOSS records for instrument+instrument_class in the
        most recent lookback_days window.  TIME_EXIT outcomes are excluded from
        the ratio computation (they don't count as wins or losses for sizing).
        """

    @abstractmethod
    async def save(self, record: SignalPerformanceRecord) -> None:
        """Append a new outcome record. Never update or delete."""
