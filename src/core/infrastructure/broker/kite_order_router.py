"""KiteOrderRouter — IOrderRouter backed by KiteBroker for live trading.

Fetches the active broker session from the repository on every call.
Raises BrokerUnavailableError if no active session exists (not logged in).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.domain.exceptions.order import BrokerUnavailableError
from core.domain.interfaces.i_order_router import IOrderRouter
from core.infrastructure.broker.order_mapper import OrderMapper

if TYPE_CHECKING:
    from core.domain.entities.order import Order
    from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository
    from core.domain.value_objects.execution_report import ExecutionReport
    from core.infrastructure.broker.kite_broker import KiteBroker

_log = logging.getLogger(__name__)

_BROKER_NAME = "kite"


class KiteOrderRouter(IOrderRouter):
    """Routes OMS orders to the live Kite Connect broker.

    Fetches the active BrokerSession from the repository on every call so
    the session can be refreshed without restarting the server.
    """

    def __init__(
        self,
        broker: KiteBroker,
        session_repository: IBrokerSessionRepository,
    ) -> None:
        self._broker = broker
        self._session_repo = session_repository
        self._mapper = OrderMapper()

    async def route(self, order: Order) -> str:
        session = await self._require_session()
        request = self._mapper.to_broker_request(order)
        broker_order_id = await self._broker.place_order(session, request)
        _log.info(
            "KiteOrderRouter.route order=%s → broker_order_id=%s",
            order.order_id,
            broker_order_id,
        )
        return broker_order_id

    async def cancel(self, order: Order) -> None:
        if not order.broker_order_id:
            _log.debug("cancel: order %s has no broker_order_id — skip", order.order_id)
            return
        session = await self._require_session()
        try:
            await self._broker.cancel_order(session, order.broker_order_id)
        except Exception:
            _log.warning(
                "KiteOrderRouter.cancel failed for broker_order_id=%s",
                order.broker_order_id,
            )

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport | None:
        session = await self._require_session()
        try:
            broker_order = await self._broker.get_order(session, broker_order_id)
        except Exception:
            _log.warning(
                "KiteOrderRouter.get_order_status failed for %s", broker_order_id
            )
            return None
        if broker_order is None:
            return None
        from core.application.services.broker.broker_execution_monitor_service import (
            BrokerExecutionMonitorService,
        )
        return BrokerExecutionMonitorService._to_execution_report(broker_order, None)

    async def _require_session(self):
        session = await self._session_repo.get_active(_BROKER_NAME)
        if session is None or not session.is_active or session.is_expired():
            msg = (
                "No active Kite session. "
                "Please authenticate via GET /api/v1/broker/login"
            )
            raise BrokerUnavailableError(msg)
        return session
