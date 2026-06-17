"""ReconciliationService — broker vs OMS reconciliation.

Responsibilities:
  1. Compare broker orders vs OMS orders (status, presence)
  2. Compare broker positions vs OMS positions (quantity, state)
  3. Detect: missing orders, orphan positions, quantity mismatches
  4. Rogue order detection → raise RogueOrderDetectedError → trigger kill switch
  5. Publish discrepancy events
  6. Run on schedule (every reconciliation.schedule_interval_seconds from config)

Security invariant: rogue broker order (not in OMS) → activate kill switch.

Caller (scheduler) provides the active BrokerSession. The reconciliation service
itself never authenticates; it only compares state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from core.domain.enums.order_state import OrderState
from core.domain.events.order_events import (
    ReconciliationCompleted,
    ReconciliationDiscrepancyDetected,
)
from core.domain.exceptions.order import RogueOrderDetectedError
from core.domain.interfaces.i_broker import IBroker
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_execution_repository import IExecutionRepository
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.interfaces.i_reconciliation_run_repository import (
    DiscrepancyFilter,
    IReconciliationRunRepository,
)

_log = logging.getLogger(__name__)

_NON_TERMINAL_STATES = {
    OrderState.PENDING,
    OrderState.SUBMITTING,
    OrderState.SUBMITTED,
    OrderState.OPEN,
    OrderState.PARTIALLY_FILLED,
}


@dataclass
class ReconciliationResult:
    ran_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    orders_checked: int = 0
    positions_checked: int = 0
    fills_checked: int = 0
    discrepancies: list[dict] = field(default_factory=list)
    rogue_orders: list[str] = field(default_factory=list)

    @property
    def discrepancy_count(self) -> int:
        return len(self.discrepancies)

    @property
    def rogue_count(self) -> int:
        return len(self.rogue_orders)


class ReconciliationService:
    """Periodic broker vs OMS reconciliation.

    Called by a background scheduler, not on the order hot path.
    Caller must provide the active BrokerSession via run(session=...).
    """

    def __init__(
        self,
        order_repository: IOrderRepository,
        position_repository: IPositionRepository,
        broker: IBroker,
        kill_switch_repository: IKillSwitchRepository,
        event_bus: IEventBus,
        execution_repository: IExecutionRepository | None = None,
        run_repository: IReconciliationRunRepository | None = None,
        broker_name: str = "unknown",
    ) -> None:
        self._order_repo = order_repository
        self._position_repo = position_repository
        self._broker = broker
        self._kill_switch = kill_switch_repository
        self._bus = event_bus
        self._exec_repo = execution_repository
        self._run_repo = run_repository
        self._broker_name = broker_name

    async def run(self, session: object, trigger: str = "SCHEDULED") -> ReconciliationResult:
        """Execute a full reconciliation pass.

        Args:
            session: Active BrokerSession (injected by scheduler).
            trigger: "SCHEDULED" or "MANUAL".

        On rogue order detection: activates kill switch before raising.
        Returns ReconciliationResult with all discrepancies found.
        """
        result = ReconciliationResult()
        run_id: int | None = None

        if self._run_repo is not None:
            try:
                run_id = await self._run_repo.start_run(self._broker_name, trigger)
            except Exception:
                _log.warning("Failed to create reconciliation run record; continuing")

        rogue_error: RogueOrderDetectedError | None = None
        try:
            await self._reconcile_orders(session, result)
            await self._reconcile_positions(session, result)
            await self._reconcile_fills(session, result)
        except RogueOrderDetectedError as e:
            rogue_error = e
        except Exception:
            _log.exception("Reconciliation run failed unexpectedly")
            if run_id is not None and self._run_repo is not None:
                try:
                    await self._run_repo.fail_run(run_id, "Unexpected error during reconciliation")
                except Exception:
                    pass
            if rogue_error is None:
                return result

        if run_id is not None and self._run_repo is not None:
            try:
                await self._run_repo.complete_run(
                    run_id=run_id,
                    orders_checked=result.orders_checked,
                    positions_checked=result.positions_checked,
                    fills_checked=result.fills_checked,
                    discrepancy_count=result.discrepancy_count,
                    rogue_count=result.rogue_count,
                    repaired_count=0,
                    discrepancies=result.discrepancies,
                )
            except Exception:
                _log.warning("Failed to persist reconciliation result")

        await self._publish_safe(
            ReconciliationCompleted(
                orders_checked=result.orders_checked,
                positions_checked=result.positions_checked,
                discrepancies_found=result.discrepancy_count,
                rogue_orders_found=result.rogue_count,
            )
        )

        _log.info(
            "Reconciliation complete: orders=%d positions=%d discrepancies=%d rogue=%d",
            result.orders_checked,
            result.positions_checked,
            result.discrepancy_count,
            result.rogue_count,
        )

        if rogue_error is not None:
            raise rogue_error
        return result

    async def list_recent_runs(
        self, limit: int = 20, offset: int = 0
    ) -> list:
        """Return recent reconciliation run records (requires run_repository)."""
        if self._run_repo is None:
            return []
        return await self._run_repo.list_runs(
            broker_name=self._broker_name, limit=limit, offset=offset
        )

    async def get_run_detail(self, run_id: int):
        """Return a single run record with discrepancies."""
        if self._run_repo is None:
            return None
        return await self._run_repo.get_run(run_id)

    async def list_discrepancies(self, filters: DiscrepancyFilter) -> tuple[list, int]:
        """Return (discrepancies, total_count) matching filters."""
        if self._run_repo is None:
            return [], 0
        items = await self._run_repo.list_discrepancies(filters)
        total = await self._run_repo.count_discrepancies(filters)
        return items, total

    # ------------------------------------------------------------------
    # Order reconciliation
    # ------------------------------------------------------------------

    async def _reconcile_orders(self, session: object, result: ReconciliationResult) -> None:
        oms_open_orders = []
        for state in _NON_TERMINAL_STATES:
            oms_open_orders.extend(await self._order_repo.get_by_state(state))

        if not oms_open_orders:
            return

        result.orders_checked = len(oms_open_orders)

        broker_orders = []
        try:
            broker_orders = await self._broker.get_orders(session)
        except Exception:
            _log.error("Failed to fetch broker orders for reconciliation")
            return

        # broker_orders is list[BrokerOrder] — treated as dicts/objects with broker_order_id
        broker_order_id_set: set[str] = set()
        for bo in broker_orders:
            bid = (
                bo.broker_order_id if hasattr(bo, "broker_order_id")
                else bo.get("broker_order_id", "")
            )
            if bid:
                broker_order_id_set.add(bid)

        for order in oms_open_orders:
            if not order.broker_order_id:
                continue  # PENDING/SUBMITTING — not yet at broker

            if order.broker_order_id not in broker_order_id_set:
                result.discrepancies.append({
                    "type": "MISSING_ORDER",
                    "order_id": str(order.order_id),
                    "broker_order_id": order.broker_order_id,
                    "oms_state": order.state.value,
                    "broker_state": "NOT_FOUND",
                })
                await self._publish_safe(
                    ReconciliationDiscrepancyDetected(
                        order_id=order.order_id,
                        broker_order_id=order.broker_order_id,
                        discrepancy_type="MISSING_ORDER",
                        oms_state=order.state.value,
                        broker_state="NOT_FOUND",
                        detail=f"OMS order {order.order_id} not found at broker",
                    )
                )

        # Rogue check: broker has orders OMS has no record of
        oms_broker_ids = {
            o.broker_order_id for o in oms_open_orders if o.broker_order_id
        }
        for bo in broker_orders:
            bid = (
                bo.broker_order_id if hasattr(bo, "broker_order_id")
                else bo.get("broker_order_id", "")
            )
            if bid and bid not in oms_broker_ids:
                result.rogue_orders.append(bid)
                _log.critical(
                    "ROGUE ORDER detected: broker_order_id=%s (not in OMS)", bid
                )
                await self._publish_safe(
                    ReconciliationDiscrepancyDetected(
                        order_id=None,
                        broker_order_id=bid,
                        discrepancy_type="ROGUE_ORDER",
                        oms_state="NOT_IN_OMS",
                        broker_state="OPEN",
                        detail=f"Broker order {bid} has no OMS record — possible external trade",
                    )
                )

        if result.rogue_orders:
            await self._activate_kill_switch(
                f"Rogue orders detected: {result.rogue_orders}"
            )
            raise RogueOrderDetectedError(
                f"Kill switch activated: {len(result.rogue_orders)} rogue "
                f"broker order(s): {result.rogue_orders}"
            )

    # ------------------------------------------------------------------
    # Position reconciliation
    # ------------------------------------------------------------------

    async def _reconcile_positions(self, session: object, result: ReconciliationResult) -> None:
        oms_open_positions = await self._position_repo.get_open_positions()

        broker_positions = []
        try:
            broker_positions = await self._broker.get_positions(session)
        except Exception:
            _log.error("Failed to fetch broker positions for reconciliation")
            return

        result.positions_checked = len(oms_open_positions)

        # Build map keyed by instrument_token
        broker_pos_map: dict[int, object] = {}
        for bp in broker_positions:
            token = (
                bp.instrument_token if hasattr(bp, "instrument_token")
                else bp.get("instrument_token", 0)
            )
            if token:
                broker_pos_map[token] = bp

        for position in oms_open_positions:
            broker_pos = broker_pos_map.get(position.instrument_token)

            if broker_pos is None:
                result.discrepancies.append({
                    "type": "ORPHAN_POSITION",
                    "position_id": str(position.position_id),
                    "instrument_token": position.instrument_token,
                })
                await self._publish_safe(
                    ReconciliationDiscrepancyDetected(
                        order_id=position.order_id,
                        broker_order_id="",
                        discrepancy_type="ORPHAN_POSITION",
                        oms_state="OPEN",
                        broker_state="NOT_FOUND",
                        detail=(
                            f"OMS position {position.position_id} "
                            f"(token={position.instrument_token}) has no broker match"
                        ),
                    )
                )
                continue

            broker_qty = (
                abs(broker_pos.net_quantity)
                if hasattr(broker_pos, "net_quantity")
                else abs(broker_pos.get("net_quantity", 0))
            )
            if broker_qty != position.quantity:
                result.discrepancies.append({
                    "type": "QTY_MISMATCH",
                    "position_id": str(position.position_id),
                    "oms_qty": position.quantity,
                    "broker_qty": broker_qty,
                })
                await self._publish_safe(
                    ReconciliationDiscrepancyDetected(
                        order_id=position.order_id,
                        broker_order_id="",
                        discrepancy_type="QTY_MISMATCH",
                        oms_state=f"qty={position.quantity}",
                        broker_state=f"qty={broker_qty}",
                        detail=(
                            f"Position {position.position_id}: "
                            f"OMS qty={position.quantity}, broker qty={broker_qty}"
                        ),
                    )
                )

            # Average price mismatch: broker vs OMS entry price (>0.5% tolerance)
            broker_avg_raw = (
                broker_pos.average_price if hasattr(broker_pos, "average_price")
                else broker_pos.get("average_price") if hasattr(broker_pos, "get") else None
            )
            if (
                isinstance(broker_avg_raw, (int, float, Decimal))
                and position.entry_price is not None
            ):
                broker_avg = Decimal(str(broker_avg_raw))
                oms_avg = position.entry_price.value
                if oms_avg > 0 and abs(broker_avg - oms_avg) / oms_avg > Decimal("0.005"):
                    result.discrepancies.append({
                        "type": "AVG_PRICE_MISMATCH",
                        "position_id": str(position.position_id),
                        "oms_avg_price": str(oms_avg),
                        "broker_avg_price": str(broker_avg),
                    })
                    await self._publish_safe(
                        ReconciliationDiscrepancyDetected(
                            order_id=position.order_id,
                            broker_order_id="",
                            discrepancy_type="AVG_PRICE_MISMATCH",
                            oms_state=f"avg={oms_avg}",
                            broker_state=f"avg={broker_avg}",
                            detail=(
                                f"Position {position.position_id}: "
                                f"OMS avg={oms_avg}, broker avg={broker_avg}"
                            ),
                        )
                    )

    # ------------------------------------------------------------------
    # Fill reconciliation
    # ------------------------------------------------------------------

    async def _reconcile_fills(self, session: object, result: ReconciliationResult) -> None:
        """Detect broker trades not recorded in OMS executions table (MISSING_FILL)."""
        if self._exec_repo is None:
            return

        oms_orders = []
        for state in _NON_TERMINAL_STATES:
            oms_orders.extend(await self._order_repo.get_by_state(state))

        broker_id_to_order = {
            o.broker_order_id: o for o in oms_orders if o.broker_order_id
        }
        if not broker_id_to_order:
            return

        try:
            broker_trades = await self._broker.get_trades(session)
        except Exception:
            _log.error("Failed to fetch broker trades for fill reconciliation")
            return

        result.fills_checked = len(broker_trades)
        for trade in broker_trades:
            broker_order_id = (
                trade.broker_order_id if hasattr(trade, "broker_order_id")
                else trade.get("broker_order_id", "")
            )
            exchange_trade_id = (
                trade.exchange_trade_id if hasattr(trade, "exchange_trade_id")
                else trade.get("exchange_trade_id", "")
            )

            if not exchange_trade_id:
                continue

            order = broker_id_to_order.get(broker_order_id)
            if order is None:
                continue  # Handled by rogue order detection

            executions = await self._exec_repo.get_by_order_id(order.order_id)
            recorded_ids = {getattr(e, "exchange_trade_id", None) for e in executions}

            if exchange_trade_id not in recorded_ids:
                result.discrepancies.append({
                    "type": "MISSING_FILL",
                    "order_id": str(order.order_id),
                    "broker_order_id": broker_order_id,
                    "exchange_trade_id": exchange_trade_id,
                })
                await self._publish_safe(
                    ReconciliationDiscrepancyDetected(
                        order_id=order.order_id,
                        broker_order_id=broker_order_id,
                        discrepancy_type="MISSING_FILL",
                        oms_state="NO_EXECUTION_RECORD",
                        broker_state=f"trade={exchange_trade_id}",
                        detail=(
                            f"Broker trade {exchange_trade_id} for order "
                            f"{broker_order_id} not in OMS executions"
                        ),
                    )
                )

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    async def _activate_kill_switch(self, reason: str) -> None:
        try:
            await self._kill_switch.activate(
                reason=reason,
                activated_by="system",
                trigger_source="reconciliation_rogue_order",
            )
            _log.critical("Kill switch ACTIVATED: %s", reason)
        except Exception:
            _log.exception("CRITICAL: Failed to activate kill switch: %s", reason)

    async def _publish_safe(self, event: object) -> None:
        try:
            await self._bus.publish(event)
        except Exception:
            _log.warning("Event publish failed for %s", type(event).__name__)
