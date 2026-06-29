"""Signal router — read and manual-override endpoints.

GET  /api/v1/signals               — list active signals (optional ?state= filter)
GET  /api/v1/signals/{signal_id}   — fetch a single signal
POST /api/v1/signals/{signal_id}/approve — manually approve (RISK_PENDING → RISK_APPROVED)
POST /api/v1/signals/{signal_id}/reject  — manually reject  (RISK_PENDING → RISK_REJECTED)
"""

import uuid
from typing import Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from container import ApplicationContainer
from core.application.services.signal_analytics_service import SignalAnalyticsService
from core.application.services.signal_scanner_service import SignalScannerService
from core.domain.enums.signal_state import SignalState
from core.domain.exceptions.signal import SignalStateError
from core.domain.interfaces.i_signal_repository import ISignalRepository
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.signal import (
    RejectSignalRequest,
    SignalListResponse,
    SignalResponse,
)

router = APIRouter(prefix="/api/v1/signals", tags=["Signals"])


def _to_response(signal: object) -> SignalResponse:
    return SignalResponse(
        signal_id=str(signal.signal_id),
        symbol=signal.symbol.ticker,
        exchange=signal.symbol.exchange,
        signal_type=signal.signal_type.value,
        strategy_type=signal.strategy_type.value,
        asset_type=signal.asset_type.value,
        regime=signal.regime.value,
        state=signal.state.value,
        confidence=signal.confidence.value if signal.confidence else None,
        adjusted_score=signal.adjusted_score.value if signal.adjusted_score else None,
        raw_score=signal.raw_score.value if signal.raw_score else None,
        valid_until=signal.valid_until,
        correlation_id=signal.correlation_id,
        risk_rejection_reason=signal.risk_rejection_reason,
        risk_profile_id=str(signal.risk_profile_id) if signal.risk_profile_id else None,
        allocation_id=str(signal.allocation_id) if signal.allocation_id else None,
        portfolio_id=str(signal.portfolio_id) if signal.portfolio_id else None,
        capital_source_mode=signal.capital_source_mode.value if signal.capital_source_mode else None,
        created_at=signal.created_at,
        entry_price=signal.entry_price,
        stop_loss_price=signal.stop_loss_price,
        target_price=signal.target_price,
        option_type=signal.option_type,
        option_strike=signal.option_strike,
        option_expiry=signal.option_expiry,
        option_symbol=signal.option_symbol,
        option_entry=signal.option_entry,
        option_sl=signal.option_sl,
        option_target=signal.option_target,
        execution_grade=signal.execution_grade,
    )


@router.get("", response_model=SignalListResponse, summary="List signals")
@inject
async def list_signals(
    state: str | None = Query(default=None, description="Filter by SignalState value"),
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    signal_repository: ISignalRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.signal_repository]
    ),
) -> SignalListResponse:
    """Return active signals, or all signals matching a specific state."""
    if state is not None:
        try:
            signal_state = SignalState(state.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state value: {state!r}",
            )
        signals = await signal_repository.get_by_state(signal_state)
    else:
        signals = await signal_repository.get_active()

    items = [_to_response(s) for s in signals]
    return SignalListResponse(signals=items, total=len(items))


@router.get("/{signal_id}", response_model=SignalResponse, summary="Get signal by ID")
@inject
async def get_signal(
    signal_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    signal_repository: ISignalRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.signal_repository]
    ),
) -> SignalResponse:
    signal = await signal_repository.get_by_id(signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found.")
    return _to_response(signal)


@router.post(
    "/{signal_id}/approve",
    response_model=SignalResponse,
    summary="Manually approve a signal (RISK_PENDING → RISK_APPROVED)",
)
@inject
async def approve_signal(
    signal_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    signal_repository: ISignalRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.signal_repository]
    ),
) -> SignalResponse:
    signal = await signal_repository.get_by_id(signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found.")
    try:
        signal.approve_risk()
    except SignalStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await signal_repository.save(signal)
    return _to_response(signal)


@router.post(
    "/{signal_id}/reject",
    response_model=SignalResponse,
    summary="Manually reject a signal (RISK_PENDING → RISK_REJECTED)",
)
@inject
async def reject_signal(
    request: Request,
    signal_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    signal_repository: ISignalRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.signal_repository]
    ),
) -> SignalResponse:
    body = RejectSignalRequest(**(await request.json()))
    signal = await signal_repository.get_by_id(signal_id)
    if signal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found.")
    try:
        signal.reject_risk(reason=body.reason)
    except SignalStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await signal_repository.save(signal)
    return _to_response(signal)


@router.get("/{signal_id}/overlay", summary="Overlay decision trace for a signal")
@inject
async def get_signal_overlay(
    signal_id: uuid.UUID,
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    svc: SignalAnalyticsService = Depends(  # noqa: B008
        Provide[ApplicationContainer.signal_analytics_service]
    ),
) -> dict[str, Any]:
    data = await svc.get_overlay_for_signal(str(signal_id))
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analytics record found for this signal.",
        )
    return data


@router.post("/scan", summary="Trigger a signal scan cycle immediately (admin)")
@inject
async def trigger_scan(
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    scanner: SignalScannerService = Depends(Provide[ApplicationContainer.signal_scanner_service]),  # noqa: B008
) -> dict:
    """Run one full universe → features → signal pipeline cycle right now."""
    return await scanner.scan_now()
