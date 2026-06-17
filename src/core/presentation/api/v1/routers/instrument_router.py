"""Instrument Master API router.

Endpoints:
    GET  /api/v1/instruments/health           — health + last sync info
    GET  /api/v1/instruments/count            — active instrument count
    POST /api/v1/instruments/sync             — trigger full sync (admin only)
    POST /api/v1/instruments/sync/incremental — trigger incremental sync (admin)
    GET  /api/v1/instruments/{token}          — lookup by broker token
    GET  /api/v1/instruments/symbol/{exchange}/{tradingsymbol} — lookup by symbol

Controllers are thin: validate input, call service, return schema.
No business logic lives here.
"""


from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from container import ApplicationContainer
from core.application.services.instrument_service import InstrumentService
from core.domain.entities.instrument import Instrument
from core.presentation.api.v1.dependencies.auth import require_admin
from core.presentation.api.v1.schemas.instrument import (
    InstrumentHealthResponse,
    InstrumentResponse,
    SyncStatusResponse,
)

router = APIRouter(prefix="/api/v1/instruments", tags=["Instruments"])


def _to_response(inst: Instrument) -> InstrumentResponse:
    return InstrumentResponse(
        token=inst.token,
        tradingsymbol=inst.symbol.ticker,
        exchange=inst.exchange,
        name=inst.name,
        segment=inst.segment,
        instrument_type=inst.instrument_type,
        asset_type=inst.asset_type.value,
        lot_size=inst.lot_size,
        tick_size=inst.tick_size.value,
        expiry=inst.expiry,
        strike=inst.strike.value if inst.strike else None,
        option_type=inst.option_type,
        underlying_symbol=inst.underlying_symbol,
        isin=inst.isin,
        is_active=inst.is_active,
    )


@router.get(
    "/health",
    response_model=InstrumentHealthResponse,
    summary="Instrument master health",
    description="Returns instrument count, last sync timestamp, and sync status.",
)
@inject
async def instrument_health(
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> InstrumentHealthResponse:
    health = await service.get_health()
    return InstrumentHealthResponse(
        instrument_count=health.instrument_count,
        last_sync_at=health.last_sync_at,
        sync_status=health.sync_status,
        provider_name=health.provider_name,
    )


@router.get(
    "/count",
    response_model=dict,
    summary="Active instrument count",
)
@inject
async def instrument_count(
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> dict[str, int]:
    count = await service.count_active()
    return {"active_instruments": count}


@router.post(
    "/sync",
    response_model=SyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger full instrument sync (admin only)",
    dependencies=[Depends(require_admin)],
)
@inject
async def trigger_full_sync(
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> SyncStatusResponse:
    result = await service.sync(full=True)
    return SyncStatusResponse(
        status=result.status.value,
        instruments_added=result.instruments_added,
        instruments_updated=result.instruments_updated,
        instruments_deactivated=result.instruments_deactivated,
        lot_size_changes_count=len(result.lot_size_changes),
        duration_ms=result.duration_ms,
        error_detail=result.error_detail,
    )


@router.post(
    "/sync/incremental",
    response_model=SyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger incremental instrument sync (admin only)",
    dependencies=[Depends(require_admin)],
)
@inject
async def trigger_incremental_sync(
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> SyncStatusResponse:
    result = await service.sync(full=False)
    return SyncStatusResponse(
        status=result.status.value,
        instruments_added=result.instruments_added,
        instruments_updated=result.instruments_updated,
        instruments_deactivated=result.instruments_deactivated,
        lot_size_changes_count=len(result.lot_size_changes),
        duration_ms=result.duration_ms,
        error_detail=result.error_detail,
    )


@router.get(
    "/{token}",
    response_model=InstrumentResponse,
    summary="Lookup instrument by broker token",
)
@inject
async def get_by_token(
    token: int,
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> InstrumentResponse:
    try:
        inst = await service.get_by_token(token)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument with token {token} not found.",
        ) from None
    return _to_response(inst)


@router.get(
    "/symbol/{exchange}/{tradingsymbol}",
    response_model=InstrumentResponse,
    summary="Lookup instrument by exchange and trading symbol",
)
@inject
async def get_by_symbol(
    exchange: str,
    tradingsymbol: str,
    service: InstrumentService = Depends(Provide[ApplicationContainer.instrument_service]),  # noqa: B008
) -> InstrumentResponse:
    try:
        inst = await service.get_by_symbol(exchange, tradingsymbol)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument {exchange}:{tradingsymbol} not found.",
        ) from None
    return _to_response(inst)
