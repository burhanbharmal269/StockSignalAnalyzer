"""ExecutionEventHandler — Phase 23 integration point.

Subscribes to existing order/signal domain events via Redis Streams
consumer group "execution_intelligence". Routes each event to the
appropriate analytics service. Non-invasive: never modifies events,
never blocks the trading pipeline.

Subscribed events:
  - SignalGenerated      → timeline.record_signal_generated
  - SignalRiskApproved   → timeline.record_risk_approved + latency record
  - OrderCreated         → timeline.record_order_created + replay
  - OrderFilled          → timeline + slippage + fill quality + replay.flush
  - OrderRejected        → rejection + replay
  - OrderCancelled       → replay
  - OrderPartiallyFilled → fill quality (partial)
  - PositionOpened       → timeline.record_position_opened
  - PositionClosed       → timeline.record_position_closed + slippage exit
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.application.services.execution_intelligence.broker_health_monitor_service import BrokerHealthMonitorService
    from core.application.services.execution_intelligence.execution_historical_service import ExecutionHistoricalService
    from core.application.services.execution_intelligence.execution_latency_service import ExecutionLatencyService
    from core.application.services.execution_intelligence.execution_rejection_service import ExecutionRejectionService
    from core.application.services.execution_intelligence.execution_replay_service import ExecutionReplayService
    from core.application.services.execution_intelligence.execution_retry_service import ExecutionRetryService
    from core.application.services.execution_intelligence.execution_slippage_service import ExecutionSlippageService
    from core.application.services.execution_intelligence.execution_timeline_service import ExecutionTimelineService

_log = logging.getLogger(__name__)


class ExecutionEventHandler:
    """Routes domain events to execution analytics services. Fail-open."""

    def __init__(
        self,
        timeline_svc: "ExecutionTimelineService",
        latency_svc: "ExecutionLatencyService",
        slippage_svc: "ExecutionSlippageService",
        retry_svc: "ExecutionRetryService",
        rejection_svc: "ExecutionRejectionService",
        replay_svc: "ExecutionReplayService",
        broker_health_svc: "BrokerHealthMonitorService",
    ) -> None:
        self._timeline = timeline_svc
        self._latency  = latency_svc
        self._slippage = slippage_svc
        self._retry    = retry_svc
        self._rejection = rejection_svc
        self._replay   = replay_svc
        self._broker_health = broker_health_svc

    # ── Signal events ─────────────────────────────────────────────────────────

    async def handle_signal_generated(self, event: Any) -> None:
        try:
            await self._timeline.record_signal_generated(
                event.signal_id,
                symbol=getattr(event, "symbol", None),
                direction=getattr(event, "signal_type", None),
                regime=getattr(event, "regime", None),
            )
            self._replay.record_event(str(event.signal_id), "signal_generated", {
                "symbol": getattr(event, "symbol", None),
                "signal_type": getattr(event, "signal_type", None),
                "strategy_type": getattr(event, "strategy_type", None),
                "regime": getattr(event, "regime", None),
            })
        except Exception as exc:
            _log.debug("exec_intel.handle_signal_generated: %s", exc)

    async def handle_signal_risk_approved(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            await self._timeline.record_risk_approved(signal_id)
            self._replay.record_event(signal_id, "risk_approved", {
                "direction": event.direction,
                "adjusted_score": event.adjusted_score,
                "regime": event.regime,
                "position_size_lots": event.position_size_lots,
            })
        except Exception as exc:
            _log.debug("exec_intel.handle_signal_risk_approved: %s", exc)

    # ── Order events ──────────────────────────────────────────────────────────

    async def handle_order_created(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            order_id  = str(event.order_id)
            await self._timeline.record_order_created(signal_id, order_id)
            self._replay.record_event(signal_id, "order_created", {
                "order_id": order_id,
                "tradingsymbol": getattr(event, "tradingsymbol", None),
                "direction": event.direction,
                "quantity": event.quantity,
                "lots": event.lots,
                "order_type": event.order_type,
            })
        except Exception as exc:
            _log.debug("exec_intel.handle_order_created: %s", exc)

    async def handle_order_filled(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            order_id  = str(event.order_id)
            ts = getattr(event, "filled_at", None)
            avg_price = float(event.average_fill_price) if event.average_fill_price else None
            qty = getattr(event, "filled_quantity", None)

            # Timeline
            await self._timeline.record_order_filled(signal_id, order_id, ts=ts)

            # Fill quality (single fill — baseline)
            await self._slippage.record_fill_quality(
                signal_id, order_id,
                fill_pct=100.0,
                num_fills=1,
                partial_fills=0,
                avg_fill_price=avg_price,
                best_fill_price=avg_price,
                worst_fill_price=avg_price,
            )

            # Latency — total execution (signal→fill)
            timeline = await self._timeline.get_timeline(signal_id)
            if timeline and timeline.get("total_execution_ms") is not None:
                await self._latency.record_stage(
                    stage="total_execution",
                    duration_ms=timeline["total_execution_ms"],
                    signal_id=signal_id,
                    order_id=order_id,
                    symbol=timeline.get("symbol"),
                    regime=timeline.get("regime"),
                )
                # Per-stage latencies
                for stage_col, stage_key in [
                    ("signal_to_risk_ms", "signal_to_risk"),
                    ("order_to_broker_ms", "order_to_broker"),
                    ("broker_to_exchange_ms", "broker_to_exchange"),
                    ("exchange_to_fill_ms", "exchange_to_fill"),
                ]:
                    val = timeline.get(stage_col)
                    if val is not None:
                        await self._latency.record_stage(
                            stage=stage_key,
                            duration_ms=val,
                            signal_id=signal_id,
                            order_id=order_id,
                            symbol=timeline.get("symbol"),
                        )

            self._replay.record_event(signal_id, "order_filled", {
                "order_id": order_id,
                "filled_quantity": qty,
                "average_fill_price": avg_price,
                "filled_at": str(ts) if ts else None,
            })
            await self._replay.flush_signal(signal_id)
        except Exception as exc:
            _log.debug("exec_intel.handle_order_filled: %s", exc)

    async def handle_order_rejected(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            order_id  = str(event.order_id)
            await self._rejection.record_rejection(
                signal_id=signal_id,
                order_id=order_id,
                broker="kite",
                rejected_by=getattr(event, "rejected_by", "oms"),
                raw_reason=getattr(event, "reason", None),
            )
            self._replay.record_error(signal_id, "order_rejected", event.reason)
            await self._replay.flush_signal(signal_id)
        except Exception as exc:
            _log.debug("exec_intel.handle_order_rejected: %s", exc)

    async def handle_order_cancelled(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            self._replay.record_event(str(event.signal_id), "order_cancelled", {
                "order_id": str(event.order_id),
                "reason": getattr(event, "reason", None),
                "cancelled_by": getattr(event, "cancelled_by", "oms"),
            })
            await self._replay.flush_signal(signal_id)
        except Exception as exc:
            _log.debug("exec_intel.handle_order_cancelled: %s", exc)

    async def handle_order_partially_filled(self, event: Any) -> None:
        try:
            order_id = str(event.order_id)
            qty      = getattr(event, "filled_quantity", 0)
            rem      = getattr(event, "remaining_quantity", 0)
            total    = qty + rem
            fill_pct = round(qty / total * 100, 2) if total else 0.0
            avg_price = float(event.average_fill_price) if event.average_fill_price else None
            await self._slippage.record_fill_quality(
                "partial_" + order_id, order_id,
                fill_pct=fill_pct,
                num_fills=1,
                partial_fills=1,
                avg_fill_price=avg_price,
            )
        except Exception as exc:
            _log.debug("exec_intel.handle_order_partially_filled: %s", exc)

    # ── Position events ───────────────────────────────────────────────────────

    async def handle_position_opened(self, event: Any) -> None:
        try:
            signal_id   = str(event.signal_id)
            position_id = str(event.position_id)
            entry_price = float(event.entry_price) if event.entry_price else None
            await self._timeline.record_position_opened(signal_id, position_id)
            # Record entry slippage context (expected = entry_price from signal, actual = fill price)
            await self._slippage.record_entry(
                signal_id, str(event.order_id),
                symbol=getattr(event, "underlying", None),
                direction=event.direction,
                lot_size=None,
                lots=event.lots,
            )
            self._replay.record_event(signal_id, "position_opened", {
                "position_id": position_id,
                "entry_price": entry_price,
                "direction": event.direction,
                "lots": event.lots,
                "regime": getattr(event, "regime_at_open", None),
            })
        except Exception as exc:
            _log.debug("exec_intel.handle_position_opened: %s", exc)

    async def handle_position_closed(self, event: Any) -> None:
        try:
            signal_id = str(event.signal_id)
            exit_price = float(event.exit_price) if event.exit_price else None
            entry_price = float(event.entry_price) if event.entry_price else None
            await self._timeline.record_position_closed(signal_id)
            # Record exit slippage
            await self._slippage.record_exit(
                signal_id,
                expected_exit=entry_price,  # approximation; real expected exit varies
                actual_exit=exit_price,
                lots=event.lots,
            )
            self._replay.record_event(signal_id, "position_closed", {
                "exit_price": exit_price,
                "realized_pnl": float(event.realized_pnl) if event.realized_pnl else None,
                "outcome": event.outcome,
            })
        except Exception as exc:
            _log.debug("exec_intel.handle_position_closed: %s", exc)
