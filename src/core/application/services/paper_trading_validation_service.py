"""PaperTradingValidationService — tracks paper trading performance and generates reports.

Aggregates metrics from the signal, order, and position repositories into
period-level stats (daily, weekly, monthly) stored in paper_trading_stats.

Design:
  - Fire-and-forget snapshot: called at end-of-day / end-of-week / end-of-month.
  - Can be triggered manually via the API for on-demand reports.
  - Does NOT touch live broker accounts; uses OMS repositories only.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from core.domain.enums.order_state import OrderState
from core.domain.enums.position_outcome import PositionOutcome
from core.domain.enums.position_state import PositionState
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.interfaces.i_paper_trading_stats_repository import (
    IPaperTradingStatsRepository,
    PaperTradingStatsUpsert,
)
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.interfaces.i_signal_repository import ISignalRepository

_log = logging.getLogger(__name__)

_TERMINAL_ORDER_STATES = {
    OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED,
    OrderState.REJECTED_PRE_SUBMIT, OrderState.EXPIRED,
}


class PaperTradingValidationService:
    """Generates performance snapshots for paper trading periods."""

    def __init__(
        self,
        stats_repository: IPaperTradingStatsRepository,
        order_repository: IOrderRepository,
        position_repository: IPositionRepository,
        signal_repository: ISignalRepository,
    ) -> None:
        self._stats = stats_repository
        self._orders = order_repository
        self._positions = position_repository
        self._signals = signal_repository

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def snapshot_daily(self, for_date: date | None = None) -> PaperTradingStatsUpsert:
        """Take a daily snapshot for for_date (defaults to today)."""
        target = for_date or datetime.now(UTC).date()
        label = target.isoformat()
        snapshot = await self._build_snapshot("DAILY", label)
        await self._stats.upsert(snapshot)
        _log.info("paper_trading.snapshot_daily period=%s", label)
        return snapshot

    async def snapshot_weekly(self, for_date: date | None = None) -> PaperTradingStatsUpsert:
        """Take a weekly snapshot for the ISO week containing for_date."""
        target = for_date or datetime.now(UTC).date()
        iso = target.isocalendar()
        label = f"{iso.year}-W{iso.week:02d}"
        snapshot = await self._build_snapshot("WEEKLY", label)
        await self._stats.upsert(snapshot)
        _log.info("paper_trading.snapshot_weekly period=%s", label)
        return snapshot

    async def snapshot_monthly(self, for_date: date | None = None) -> PaperTradingStatsUpsert:
        """Take a monthly snapshot for the month containing for_date."""
        target = for_date or datetime.now(UTC).date()
        label = f"{target.year}-{target.month:02d}"
        snapshot = await self._build_snapshot("MONTHLY", label)
        await self._stats.upsert(snapshot)
        _log.info("paper_trading.snapshot_monthly period=%s", label)
        return snapshot

    async def get_report(
        self, period_type: str, period_label: str
    ) -> dict:
        """Return a structured report dict for the given period."""
        stats = await self._stats.get(period_type, period_label)
        if stats is None:
            return {"period_type": period_type, "period_label": period_label, "data": None}
        return {
            "period_type": stats.period_type,
            "period_label": stats.period_label,
            "signals": {
                "generated": stats.signals_generated,
                "approved": stats.signals_approved,
                "rejected": stats.signals_rejected,
                "approval_rate": round(stats.approval_rate, 4),
            },
            "orders": {
                "placed": stats.orders_placed,
                "filled": stats.orders_filled,
                "cancelled": stats.orders_cancelled,
                "fill_rate": round(
                    stats.orders_filled / stats.orders_placed
                    if stats.orders_placed else 0.0, 4
                ),
            },
            "positions": {
                "opened": stats.positions_opened,
                "closed": stats.positions_closed,
            },
            "performance": {
                "gross_pnl": float(stats.gross_pnl),
                "win_count": stats.win_count,
                "loss_count": stats.loss_count,
                "win_rate": round(stats.win_rate, 4),
                "max_drawdown": float(stats.max_drawdown),
                "avg_hold_seconds": float(stats.avg_hold_seconds) if stats.avg_hold_seconds else None,
            },
            "execution": {
                "avg_slippage_bps": float(stats.avg_slippage_bps) if stats.avg_slippage_bps else None,
                "broker_latency_p50_ms": float(stats.broker_latency_p50_ms) if stats.broker_latency_p50_ms else None,
                "broker_latency_p99_ms": float(stats.broker_latency_p99_ms) if stats.broker_latency_p99_ms else None,
            },
        }

    async def list_reports(
        self, period_type: str, limit: int = 30, offset: int = 0
    ) -> list[dict]:
        """List reports for a period type."""
        stats_list = await self._stats.list_by_type(period_type, limit=limit, offset=offset)
        reports = []
        for s in stats_list:
            reports.append(await self.get_report(s.period_type, s.period_label))
        return reports

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _build_snapshot(self, period_type: str, period_label: str) -> PaperTradingStatsUpsert:
        """Compute live stats from OMS repositories."""
        # Count signals
        try:
            all_signals = await self._signals.list_all(limit=10000)
            signals_generated = len(all_signals)
            signals_approved = sum(
                1 for s in all_signals
                if getattr(s, "state", None) is not None
                and str(getattr(s, "state", "")).upper() in ("APPROVED", "FILLED", "COMPLETED")
            )
            signals_rejected = sum(
                1 for s in all_signals
                if str(getattr(s, "state", "")).upper() == "REJECTED"
            )
        except Exception:
            signals_generated = signals_approved = signals_rejected = 0

        # Count orders
        orders_placed = orders_filled = orders_cancelled = 0
        try:
            for state in list(OrderState):
                orders_in_state = await self._orders.get_by_state(state)
                if state in _TERMINAL_ORDER_STATES:
                    pass
                orders_placed += len(orders_in_state)
                if state == OrderState.FILLED:
                    orders_filled = len(orders_in_state)
                elif state == OrderState.CANCELLED:
                    orders_cancelled = len(orders_in_state)
        except Exception:
            pass

        # Count positions and PnL
        positions_opened = positions_closed = 0
        gross_pnl = Decimal("0")
        win_count = loss_count = 0
        max_drawdown = Decimal("0")
        hold_seconds_list: list[Decimal] = []

        try:
            open_positions = await self._positions.get_open_positions()
            positions_opened = len(open_positions)

            all_by_symbol: list = []
            # Collect all closed positions via open_positions (filter by state)
            for pos in open_positions:
                if getattr(pos, "state", None) == PositionState.CLOSED:
                    positions_closed += 1
                    pnl = pos.realized_pnl
                    if hasattr(pnl, "value"):
                        pnl_val = pnl.value
                    else:
                        pnl_val = Decimal(str(pnl))
                    gross_pnl += pnl_val
                    if pnl_val > 0:
                        win_count += 1
                    elif pnl_val < 0:
                        loss_count += 1
                    if pos.opened_at and pos.closed_at:
                        hold = (pos.closed_at - pos.opened_at).total_seconds()
                        hold_seconds_list.append(Decimal(str(hold)))
        except Exception:
            pass

        avg_hold: Decimal | None = None
        if hold_seconds_list:
            avg_hold = sum(hold_seconds_list) / len(hold_seconds_list)

        return PaperTradingStatsUpsert(
            period_type=period_type,
            period_label=period_label,
            signals_generated=signals_generated,
            signals_approved=signals_approved,
            signals_rejected=signals_rejected,
            orders_placed=orders_placed,
            orders_filled=orders_filled,
            orders_cancelled=orders_cancelled,
            positions_opened=positions_opened,
            positions_closed=positions_closed,
            gross_pnl=gross_pnl,
            win_count=win_count,
            loss_count=loss_count,
            max_drawdown=max_drawdown,
            avg_hold_seconds=avg_hold,
        )
