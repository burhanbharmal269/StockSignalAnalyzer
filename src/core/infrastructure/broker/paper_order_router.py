"""PaperOrderRouter — IOrderRouter backed by PaperBrokerAdapter.

Routes OMS Order objects to the paper broker for simulation without
touching real money or a live exchange. The paper broker fills orders
instantly at LTP ± slippage.

OMS never imports PaperBrokerAdapter directly — it depends on IOrderRouter.
This adapter is the only place that knows about PaperBrokerAdapter.
"""

from __future__ import annotations

import logging

from core.domain.entities.broker_session import BrokerSession
from core.domain.entities.order import Order
from core.domain.interfaces.i_order_router import IOrderRouter
from core.domain.value_objects.execution_report import ExecutionReport
from core.infrastructure.broker.order_mapper import OrderMapper
from core.infrastructure.broker.paper_broker import PaperBrokerAdapter

_log = logging.getLogger(__name__)

_PAPER_SESSION_KEY = "paper"


class PaperOrderRouter(IOrderRouter):
    """Routes orders to the in-memory paper broker.

    A lazily-initialised paper session is held for the lifetime of this
    router instance. The session never expires (BrokerSession.expires_at=2099)
    so no token-refresh flow is needed.
    """

    def __init__(self, broker: PaperBrokerAdapter) -> None:
        self._broker = broker
        self._mapper = OrderMapper()
        self._session: BrokerSession | None = None

    # ------------------------------------------------------------------
    # IOrderRouter
    # ------------------------------------------------------------------

    async def route(self, order: Order) -> str:
        """Submit order to paper broker. Returns broker_order_id immediately.

        The paper broker fills all orders instantly at LTP ± slippage.
        Raises BrokerUnavailableError only if the broker adapter itself raises.
        """
        session = await self._get_session()
        request = self._mapper.to_broker_request(order)
        broker_order_id = await self._broker.place_order(session, request)
        _log.debug(
            "PaperOrderRouter.route order=%s → broker_order_id=%s",
            order.order_id,
            broker_order_id,
        )
        return broker_order_id

    async def cancel(self, order: Order) -> None:
        """Cancel an open paper order. Cancellations bypass kill switch."""
        if not order.broker_order_id:
            _log.debug("cancel: order %s has no broker_order_id — skip", order.order_id)
            return
        session = await self._get_session()
        try:
            await self._broker.cancel_order(session, order.broker_order_id)
        except Exception:
            _log.warning(
                "PaperOrderRouter.cancel failed for broker_order_id=%s",
                order.broker_order_id,
            )

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport | None:
        """Fetch paper order status and translate to ExecutionReport."""
        session = await self._get_session()
        try:
            broker_order = await self._broker.get_order(session, broker_order_id)
        except Exception:
            _log.warning(
                "PaperOrderRouter.get_order_status failed for %s", broker_order_id
            )
            return None
        if broker_order is None:
            return None
        # Reuse the static translator from BrokerExecutionMonitorService
        from core.application.services.broker.broker_execution_monitor_service import (
            BrokerExecutionMonitorService,
        )
        return BrokerExecutionMonitorService._to_execution_report(broker_order, None)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_session(self) -> BrokerSession:
        if self._session is None or not self._session.is_active:
            self._session = await self._broker.login(
                api_key=_PAPER_SESSION_KEY,
                request_token=_PAPER_SESSION_KEY,
                api_secret=_PAPER_SESSION_KEY,
            )
            _log.info("PaperOrderRouter: paper session initialised")
        return self._session
