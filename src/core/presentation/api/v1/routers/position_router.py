"""Position router — read and manual-close endpoints.

GET  /api/v1/positions                    — list open/partially-closed positions
GET  /api/v1/positions/{position_id}      — fetch a single position
POST /api/v1/positions/{position_id}/close — manually close a position at given price
"""

from __future__ import annotations

import uuid

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from container import ApplicationContainer
from core.domain.enums.position_state import PositionState
from core.domain.interfaces.i_position_repository import IPositionRepository
from core.domain.value_objects.price import Price
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.position import (
    ClosePositionRequest,
    PositionListResponse,
    PositionResponse,
)

router = APIRouter(prefix="/api/v1/positions", tags=["Positions"])


def _to_response(position: object) -> PositionResponse:
    return PositionResponse(
        position_id=str(position.position_id),
        signal_id=str(position.signal_id) if position.signal_id else None,
        order_id=str(position.order_id) if position.order_id else None,
        symbol=position.symbol.ticker,
        exchange=position.symbol.exchange,
        direction=position.direction.value,
        quantity=position.quantity,
        entry_price=float(position.entry_price.value),
        current_price=float(position.current_price.value),
        state=position.state.value,
        realized_pnl=float(position.realized_pnl.value),
        current_mtm_pnl=float(position.current_mtm_pnl.value),
        unrealized_pnl=float(position.unrealized_pnl.value),
        total_pnl=float(position.total_pnl.value),
        trading_mode=position.trading_mode.value,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
    )


@router.get("", response_model=PositionListResponse, summary="List open positions")
@inject
async def list_positions(
    trading_mode: str | None = Query(default=None, description="Filter by trading mode: PAPER or LIVE"),
    state: str | None = Query(default=None, description="Filter by state: OPEN, PARTIALLY_CLOSED, CLOSED"),
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    position_repository: IPositionRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.position_repository]
    ),
) -> PositionListResponse:
    positions = await position_repository.get_open_positions()
    if trading_mode is not None:
        positions = [p for p in positions if p.trading_mode.value.upper() == trading_mode.upper()]
    if state is not None:
        try:
            target_state = PositionState(state.upper())
            positions = [p for p in positions if p.state == target_state]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state value: {state!r}",
            )
    items = [_to_response(p) for p in positions]
    return PositionListResponse(positions=items, total=len(items))


@router.get(
    "/{position_id}", response_model=PositionResponse, summary="Get position by ID"
)
@inject
async def get_position(
    position_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    position_repository: IPositionRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.position_repository]
    ),
) -> PositionResponse:
    position = await position_repository.get_by_id(position_id)
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    return _to_response(position)


@router.post(
    "/{position_id}/close",
    response_model=PositionResponse,
    summary="Manually close an open position",
)
@inject
async def close_position(
    position_id: uuid.UUID,
    body: ClosePositionRequest,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    position_repository: IPositionRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.position_repository]
    ),
) -> PositionResponse:
    position = await position_repository.get_by_id(position_id)
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    if position.state == PositionState.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Position is already closed.",
        )
    try:
        exit_price = Price(body.exit_price)
        position.close(exit_price=exit_price, closed_quantity=position.quantity)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    await position_repository.save(position)
    return _to_response(position)
