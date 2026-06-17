"""Market Regime Engine API router.

Endpoints:
    GET /api/v1/regime/{token}/{timeframe}/latest  — latest regime snapshot
    GET /api/v1/regime/{token}/{timeframe}/history — regime history (since query param)

Controllers are thin: validate input, call repository, return schema.
No business logic lives here.
"""


from datetime import UTC, datetime, timedelta

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from container import ApplicationContainer
from core.domain.interfaces.i_regime_repository import IRegimeRepository
from core.domain.value_objects.regime_snapshot import RegimeSnapshot
from core.presentation.api.v1.schemas.regime import (
    RegimeHistoryResponse,
    RegimeSnapshotResponse,
)

router = APIRouter(prefix="/api/v1/regime", tags=["Market Regime"])


def _to_response(snap: RegimeSnapshot) -> RegimeSnapshotResponse:
    return RegimeSnapshotResponse(
        instrument_token=snap.instrument_token,
        timeframe=snap.timeframe,
        primary_regime=snap.primary_regime,
        secondary_regime=snap.secondary_regime,
        direction_layer=snap.direction_layer,
        volatility_layer=snap.volatility_layer,
        confidence=snap.confidence,
        score=snap.score,
        stability_score=snap.stability_score,
        regime_duration_bars=snap.regime_duration_bars,
        transition_signal=snap.transition_signal,
        explanation=list(snap.explanation),
        evaluated_at=snap.evaluated_at,
    )


@router.get(
    "/{instrument_token}/{timeframe}/latest",
    response_model=RegimeSnapshotResponse,
    summary="Get latest regime snapshot",
)
@inject
async def get_latest_regime(
    instrument_token: int,
    timeframe: str,
    regime_repository: IRegimeRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.regime_repository]
    ),
) -> RegimeSnapshotResponse:
    snapshot = await regime_repository.get_latest(instrument_token, timeframe)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No regime snapshot found for"
                f" token={instrument_token}, timeframe={timeframe}"
            ),
        )
    return _to_response(snapshot)


@router.get(
    "/{instrument_token}/{timeframe}/history",
    response_model=RegimeHistoryResponse,
    summary="Get regime history",
)
@inject
async def get_regime_history(
    instrument_token: int,
    timeframe: str,
    hours: int = Query(default=24, ge=1, le=720),
    regime_repository: IRegimeRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.regime_repository]
    ),
) -> RegimeHistoryResponse:
    since = datetime.now(UTC) - timedelta(hours=hours)
    snapshots = await regime_repository.get_history(instrument_token, timeframe, since)
    return RegimeHistoryResponse(
        instrument_token=instrument_token,
        timeframe=timeframe,
        snapshots=[_to_response(s) for s in snapshots],
    )
