"""IPaperTradingStatsRepository — port for paper trading performance stats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class PaperTradingStats:
    stat_id: int
    period_type: str  # DAILY | WEEKLY | MONTHLY
    period_label: str  # e.g. "2026-06-15" / "2026-W24" / "2026-06"
    signals_generated: int
    signals_approved: int
    signals_rejected: int
    orders_placed: int
    orders_filled: int
    orders_cancelled: int
    positions_opened: int
    positions_closed: int
    gross_pnl: Decimal
    win_count: int
    loss_count: int
    max_drawdown: Decimal
    avg_hold_seconds: Decimal | None
    avg_slippage_bps: Decimal | None
    broker_latency_p50_ms: Decimal | None
    broker_latency_p99_ms: Decimal | None
    snapshot: dict | None
    created_at: datetime

    @property
    def total_trades(self) -> int:
        return self.win_count + self.loss_count

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.win_count / self.total_trades

    @property
    def approval_rate(self) -> float:
        if self.signals_generated == 0:
            return 0.0
        return self.signals_approved / self.signals_generated


@dataclass
class PaperTradingStatsUpsert:
    period_type: str
    period_label: str
    signals_generated: int = 0
    signals_approved: int = 0
    signals_rejected: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    gross_pnl: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    max_drawdown: Decimal = Decimal("0")
    avg_hold_seconds: Decimal | None = None
    avg_slippage_bps: Decimal | None = None
    broker_latency_p50_ms: Decimal | None = None
    broker_latency_p99_ms: Decimal | None = None
    snapshot: dict | None = None


class IPaperTradingStatsRepository(ABC):
    @abstractmethod
    async def upsert(self, stats: PaperTradingStatsUpsert) -> None:
        """Insert or update stats for a given period."""

    @abstractmethod
    async def get(self, period_type: str, period_label: str) -> PaperTradingStats | None:
        """Retrieve stats for an exact period."""

    @abstractmethod
    async def list_by_type(
        self, period_type: str, limit: int = 30, offset: int = 0
    ) -> list[PaperTradingStats]:
        """Return periods of a given type (newest first)."""
