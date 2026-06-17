"""Order router — read and cancel endpoints.

GET  /api/v1/orders              — list orders (optional ?state= filter, ?limit=, ?offset=)
GET  /api/v1/orders/{order_id}   — fetch a single order
POST /api/v1/orders/{order_id}/cancel — cancel an active order
"""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from container import ApplicationContainer
from core.domain.enums.order_state import OrderState
from core.domain.exceptions.order import OrderStateError
from core.domain.interfaces.i_order_repository import IOrderRepository
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.order import OrderListResponse, OrderResponse

router = APIRouter(prefix="/api/v1/orders", tags=["Orders"])


def _to_response(order: object) -> OrderResponse:
    return OrderResponse(
        order_id=str(order.order_id),
        signal_id=str(order.signal_id) if order.signal_id else None,
        tradingsymbol=order.tradingsymbol,
        symbol=order.symbol.ticker,
        exchange=order.symbol.exchange,
        transaction_type=order.transaction_type.value,
        order_type=order.order_type.value,
        product=order.product.value,
        quantity=order.quantity,
        lots=order.lots,
        limit_price=float(order.limit_price.value) if order.limit_price else None,
        trigger_price=float(order.trigger_price.value) if order.trigger_price else None,
        state=order.state.value,
        broker_order_id=order.broker_order_id,
        filled_quantity=order.filled_quantity,
        average_fill_price=float(order.average_fill_price.value) if order.average_fill_price else None,
        rejection_reason=order.rejection_reason,
        trading_mode=order.trading_mode.value,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.get("", response_model=OrderListResponse, summary="List orders")
@inject
async def list_orders(
    state: str | None = Query(default=None, description="Filter by OrderState value"),
    trading_mode: str | None = Query(default=None, description="Filter by trading mode: PAPER or LIVE"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    order_repository: IOrderRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.order_repository]
    ),
) -> OrderListResponse:
    if state is not None:
        try:
            order_state = OrderState(state.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state value: {state!r}",
            )
        orders = await order_repository.get_by_state(order_state)
    else:
        orders = await order_repository.list_all(limit=limit, offset=offset)

    if trading_mode is not None:
        orders = [o for o in orders if o.trading_mode.value.upper() == trading_mode.upper()]

    items = [_to_response(o) for o in orders]
    return OrderListResponse(orders=items, total=len(items))


@router.get("/{order_id}", response_model=OrderResponse, summary="Get order by ID")
@inject
async def get_order(
    order_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    order_repository: IOrderRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.order_repository]
    ),
) -> OrderResponse:
    order = await order_repository.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return _to_response(order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an active order",
)
@inject
async def cancel_order(
    order_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    order_repository: IOrderRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.order_repository]
    ),
) -> OrderResponse:
    order = await order_repository.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    try:
        order.cancel(reason="Manual cancel via API")
    except OrderStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await order_repository.save(order)
    return _to_response(order)
