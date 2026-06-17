"""Unit tests for OrderMapper."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

from core.domain.enums.order_type import OrderType
from core.domain.enums.product_type import ProductType
from core.domain.enums.transaction_type import TransactionType
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol
from core.infrastructure.broker.order_mapper import OrderMapper


def _make_order(
    transaction_type: TransactionType = TransactionType.BUY,
    order_type: OrderType = OrderType.MARKET,
    product: ProductType = ProductType.MIS,
    qty: int = 50,
    limit_price: Decimal | None = None,
    trigger_price: Decimal | None = None,
) -> MagicMock:
    order = MagicMock()
    order.signal_id = uuid.uuid4()
    order.symbol = Symbol(ticker="NIFTY", exchange="NFO")
    order.quantity = qty
    order.transaction_type = transaction_type
    order.order_type = order_type
    order.product = product
    order.limit_price = Price(limit_price) if limit_price else None
    order.trigger_price = Price(trigger_price) if trigger_price else None
    return order


class TestOrderMapperDirections:
    def test_buy_maps_to_buy(self) -> None:
        order = _make_order(transaction_type=TransactionType.BUY)
        req = OrderMapper.to_broker_request(order)
        assert req.direction == "BUY"

    def test_sell_maps_to_sell(self) -> None:
        order = _make_order(transaction_type=TransactionType.SELL)
        req = OrderMapper.to_broker_request(order)
        assert req.direction == "SELL"


class TestOrderMapperOrderTypes:
    def test_market_maps_to_market(self) -> None:
        order = _make_order(order_type=OrderType.MARKET)
        req = OrderMapper.to_broker_request(order)
        assert req.order_type == "MARKET"

    def test_limit_maps_to_limit(self) -> None:
        order = _make_order(order_type=OrderType.LIMIT, limit_price=Decimal("21990"))
        req = OrderMapper.to_broker_request(order)
        assert req.order_type == "LIMIT"
        assert req.limit_price == Decimal("21990")

    def test_sl_maps_to_sl_limit(self) -> None:
        order = _make_order(
            order_type=OrderType.SL,
            limit_price=Decimal("21900"),
            trigger_price=Decimal("21950"),
        )
        req = OrderMapper.to_broker_request(order)
        assert req.order_type == "SL_LIMIT"
        assert req.trigger_price == Decimal("21950")

    def test_sl_market_maps_to_sl_market(self) -> None:
        order = _make_order(
            order_type=OrderType.SL_MARKET,
            trigger_price=Decimal("21950"),
        )
        req = OrderMapper.to_broker_request(order)
        assert req.order_type == "SL_MARKET"


class TestOrderMapperProducts:
    def test_mis_maps_to_intraday(self) -> None:
        order = _make_order(product=ProductType.MIS)
        req = OrderMapper.to_broker_request(order)
        assert req.product == "INTRADAY"

    def test_nrml_maps_to_overnight(self) -> None:
        order = _make_order(product=ProductType.NRML)
        req = OrderMapper.to_broker_request(order)
        assert req.product == "OVERNIGHT"

    def test_cnc_maps_to_delivery(self) -> None:
        order = _make_order(product=ProductType.CNC)
        req = OrderMapper.to_broker_request(order)
        assert req.product == "DELIVERY"


class TestOrderMapperFields:
    def test_symbol_and_exchange_copied(self) -> None:
        order = _make_order()
        req = OrderMapper.to_broker_request(order)
        assert req.symbol == "NIFTY"
        assert req.exchange == "NFO"

    def test_quantity_copied(self) -> None:
        order = _make_order(qty=100)
        req = OrderMapper.to_broker_request(order)
        assert req.quantity == 100

    def test_tag_defaults_to_signal_id_prefix(self) -> None:
        order = _make_order()
        req = OrderMapper.to_broker_request(order)
        assert req.tag == str(order.signal_id)[:8]

    def test_custom_tag_overrides_default(self) -> None:
        order = _make_order()
        req = OrderMapper.to_broker_request(order, tag="my_tag")
        assert req.tag == "my_tag"

    def test_no_limit_price_on_market_order(self) -> None:
        order = _make_order(order_type=OrderType.MARKET)
        req = OrderMapper.to_broker_request(order)
        assert req.limit_price is None
