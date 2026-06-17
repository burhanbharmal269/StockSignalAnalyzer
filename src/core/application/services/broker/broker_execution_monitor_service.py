"""BrokerExecutionMonitorService — polls broker and feeds ExecutionReports to OMS.

Responsibilities:
  1. Get all SUBMITTED/OPEN/PARTIALLY_FILLED orders from OMS order repository.
  2. For each OMS order with a broker_order_id, call broker.get_order().
  3. Translate broker order status to an ExecutionReport.
  4. Feed reports into ExecutionMonitorService.process_execution_report().

This service bridges the broker adapter (IBroker) with the OMS execution monitor.
It does NOT own the fill logic — that is in ExecutionMonitorService (Phase 15).

IBrokerExecutionMonitor implementation for the direct-broker polling path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.enums.order_state import OrderState
from core.domain.interfaces.i_broker_execution_monitor import IBrokerExecutionMonitor
from core.domain.value_objects.broker_dtos import BrokerMargin, BrokerPosition
from core.domain.value_objects.execution_report import ExecutionReport
from core.domain.value_objects.price import Price

if TYPE_CHECKING:
    from core.application.services.oms.execution_monitor_service import ExecutionMonitorService
    from core.domain.interfaces.i_broker import IBroker
    from core.domain.interfaces.i_order_repository import IOrderRepository

_log = logging.getLogger(__name__)

_MONITORABLE_STATES = {OrderState.SUBMITTED, OrderState.OPEN, OrderState.PARTIALLY_FILLED}

# Kite/broker status strings → execution report classification
_FILL_STATUSES = {"COMPLETE", "FILLED"}
_PARTIAL_STATUSES = {"OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED"}
_REJECT_STATUSES = {"REJECTED", "CANCELLED"}


class BrokerExecutionMonitorService(IBrokerExecutionMonitor):
    """Polls broker for order updates and routes them through OMS.

    Acts as the IBrokerExecutionMonitor implementation using direct IBroker calls.
    """

    def __init__(
        self,
        broker: IBroker,
        order_repository: IOrderRepository,
        execution_monitor: ExecutionMonitorService,
    ) -> None:
        self._broker = broker
        self._order_repo = order_repository
        self._exec_monitor = execution_monitor

    async def poll_and_process(self, session: object) -> int:
        """Poll broker for all active OMS orders and process any status changes.

        Returns the number of orders updated.
        """
        reports = await self.monitor_orders(session)
        updated = 0
        for report in reports:
            try:
                order = await self._exec_monitor.process_execution_report(report)
                if order is not None:
                    updated += 1
            except Exception:
                _log.exception(
                    "Error processing report for broker_order_id=%s",
                    report.broker_order_id,
                )
        return updated

    async def monitor_orders(self, session: object) -> list[ExecutionReport]:
        """IBrokerExecutionMonitor: poll broker orders for active OMS orders."""
        oms_orders = []
        for state in _MONITORABLE_STATES:
            oms_orders.extend(await self._order_repo.get_by_state(state))

        reports: list[ExecutionReport] = []
        for order in oms_orders:
            if not order.broker_order_id:
                continue
            try:
                broker_order = await self._broker.get_order(session, order.broker_order_id)
            except Exception:
                _log.warning("Failed to get order %s from broker", order.broker_order_id)
                continue
            if broker_order is None:
                continue
            report = self._to_execution_report(broker_order, order.order_id)
            if report is not None:
                reports.append(report)
        return reports

    async def monitor_positions(self, session: object) -> list[BrokerPosition]:
        """IBrokerExecutionMonitor: return current broker positions."""
        try:
            return await self._broker.get_positions(session)
        except Exception:
            _log.error("BrokerExecutionMonitorService.monitor_positions failed")
            return []

    async def monitor_margin(self, session: object) -> BrokerMargin:
        """IBrokerExecutionMonitor: return current broker margin."""
        try:
            return await self._broker.get_margin(session)
        except Exception:
            _log.error("BrokerExecutionMonitorService.monitor_margin failed")
            return BrokerMargin(
                available_cash=Decimal("0"),
                used_margin=Decimal("0"),
                total_margin=Decimal("0"),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_execution_report(broker_order: object, oms_order_id: object) -> ExecutionReport | None:
        broker_order_id = getattr(broker_order, "broker_order_id", "")
        status = getattr(broker_order, "status", "")
        filled_qty = getattr(broker_order, "filled_quantity", 0) or 0
        total_qty = getattr(broker_order, "quantity", 0) or 0
        avg_price = getattr(broker_order, "average_price", None)
        now = datetime.now(UTC)

        if status in _FILL_STATUSES and filled_qty > 0:
            fill_price = Price(avg_price) if avg_price else None
            return ExecutionReport(
                broker_order_id=broker_order_id,
                oms_order_id=oms_order_id,
                status="COMPLETE",
                filled_quantity=filled_qty,
                remaining_quantity=0,
                average_fill_price=fill_price,
                last_fill_price=fill_price,
                last_fill_quantity=filled_qty,
                exchange_trade_id="",
                reported_at=now,
                rejection_reason="",
                trading_mode="PAPER",
            )

        if status in _PARTIAL_STATUSES and 0 < filled_qty < total_qty:
            fill_price = Price(avg_price) if avg_price else None
            return ExecutionReport(
                broker_order_id=broker_order_id,
                oms_order_id=oms_order_id,
                status="UPDATE",
                filled_quantity=filled_qty,
                remaining_quantity=total_qty - filled_qty,
                average_fill_price=fill_price,
                last_fill_price=fill_price,
                last_fill_quantity=filled_qty,
                exchange_trade_id="",
                reported_at=now,
                rejection_reason="",
                trading_mode="PAPER",
            )

        if status in _REJECT_STATUSES:
            return ExecutionReport(
                broker_order_id=broker_order_id,
                oms_order_id=oms_order_id,
                status="REJECTED",
                filled_quantity=filled_qty,
                remaining_quantity=total_qty - filled_qty,
                average_fill_price=None,
                last_fill_price=None,
                last_fill_quantity=0,
                exchange_trade_id="",
                reported_at=now,
                rejection_reason=status,
                trading_mode="PAPER",
            )

        return None
