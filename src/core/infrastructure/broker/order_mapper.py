"""OrderMapper — translates OMS Order to BrokerOrderRequest.

Maps internal OMS enums to broker-agnostic strings that IBroker adapters
can then map to broker-specific codes (e.g. Kite's MIS/NRML/CNC).

OMS direction LONG → BUY, SHORT → SELL.
OMS OrderType → broker order_type string.
OMS ProductType → broker product string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.transaction_type import TransactionType
from core.domain.value_objects.broker_dtos import BrokerOrderRequest

if TYPE_CHECKING:
    from core.domain.entities.order import Order

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL_LIMIT",
    OrderType.SL_MARKET: "SL_MARKET",
}

_PRODUCT_MAP: dict[ProductType, str] = {
    ProductType.MIS: "INTRADAY",
    ProductType.NRML: "OVERNIGHT",
    ProductType.CNC: "DELIVERY",
}

_DIRECTION_MAP: dict[TransactionType, str] = {
    TransactionType.BUY: "BUY",
    TransactionType.SELL: "SELL",
}


class OrderMapper:
    """Stateless mapper: OMS Order → BrokerOrderRequest."""

    @staticmethod
    def to_broker_request(order: Order, tag: str = "") -> BrokerOrderRequest:
        """Convert an OMS Order to a BrokerOrderRequest.

        Args:
            order: The OMS Order entity to convert.
            tag: Optional broker tag/label (defaults to signal_id prefix).

        Returns:
            BrokerOrderRequest ready for IBroker.place_order().
        """
        direction = _DIRECTION_MAP.get(order.transaction_type, "BUY")
        order_type = _ORDER_TYPE_MAP.get(order.order_type, "MARKET")
        product = _PRODUCT_MAP.get(order.product, "INTRADAY")
        tag = tag or str(order.signal_id)[:8]

        limit_price = order.limit_price.value if order.limit_price else None
        trigger_price = order.trigger_price.value if order.trigger_price else None

        return BrokerOrderRequest(
            symbol=order.symbol.ticker,
            exchange=order.symbol.exchange,
            direction=direction,
            quantity=order.quantity,
            order_type=order_type,
            product=product,
            limit_price=limit_price,
            trigger_price=trigger_price,
            tag=tag,
        )
