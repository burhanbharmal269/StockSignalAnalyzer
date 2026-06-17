"""Reconciliation dashboard router.

GET  /api/v1/reconciliation/runs             — list recent runs
GET  /api/v1/reconciliation/runs/{run_id}    — single run with discrepancies
GET  /api/v1/reconciliation/discrepancies    — query discrepancies across runs
POST /api/v1/reconciliation/trigger          — manual reconciliation trigger
"""


import logging
from datetime import datetime

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from container import ApplicationContainer
from core.application.services.broker.broker_reconciliation_service import (
    BrokerReconciliationService,
)
from core.domain.interfaces.i_reconciliation_run_repository import DiscrepancyFilter
from core.presentation.api.v1.dependencies.auth import require_admin, require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.reconciliation import (
    ManualTriggerResponse,
    ReconciliationDiscrepancyListResponse,
    ReconciliationDiscrepancySchema,
    ReconciliationRunListResponse,
    ReconciliationRunSchema,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reconciliation", tags=["Reconciliation"])


@router.get(
    "/runs",
    response_model=ReconciliationRunListResponse,
    summary="List recent reconciliation runs",
)
@inject
async def list_reconciliation_runs(
    broker_name: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    reconciliation_service: BrokerReconciliationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_reconciliation_service]
    ),
) -> ReconciliationRunListResponse:
    runs = await reconciliation_service._reconciliation.list_recent_runs(
        limit=limit, offset=offset
    )
    return ReconciliationRunListResponse(
        runs=[ReconciliationRunSchema.model_validate(r.__dict__) for r in runs],
        total=len(runs),
    )


@router.get(
    "/runs/{run_id}",
    response_model=ReconciliationRunSchema,
    summary="Get reconciliation run detail with discrepancies",
)
@inject
async def get_reconciliation_run(
    run_id: int,
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    reconciliation_service: BrokerReconciliationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_reconciliation_service]
    ),
) -> ReconciliationRunSchema:
    run = await reconciliation_service._reconciliation.get_run_detail(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return ReconciliationRunSchema.model_validate(run.__dict__ | {
        "discrepancies": [d.__dict__ for d in run.discrepancies]
    })


@router.get(
    "/discrepancies",
    response_model=ReconciliationDiscrepancyListResponse,
    summary="Query reconciliation discrepancies across all runs",
)
@inject
async def list_discrepancies(
    discrepancy_type: str | None = Query(default=None),
    repaired: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    reconciliation_service: BrokerReconciliationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_reconciliation_service]
    ),
) -> ReconciliationDiscrepancyListResponse:
    filters = DiscrepancyFilter(
        discrepancy_type=discrepancy_type,
        repaired=repaired,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    items, total = await reconciliation_service._reconciliation.list_discrepancies(filters)
    return ReconciliationDiscrepancyListResponse(
        discrepancies=[ReconciliationDiscrepancySchema.model_validate(d.__dict__) for d in items],
        total=total,
    )


@router.post(
    "/trigger",
    response_model=ManualTriggerResponse,
    summary="Manually trigger a reconciliation run (admin only)",
)
@inject
async def trigger_reconciliation(
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    reconciliation_service: BrokerReconciliationService = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_reconciliation_service]
    ),
) -> ManualTriggerResponse:
    result = await reconciliation_service.run(trigger="MANUAL")
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active broker session — reconciliation skipped",
        )
    return ManualTriggerResponse(
        message="Reconciliation completed",
        broker_name=reconciliation_service._broker_name,
        orders_checked=result.orders_checked,
        positions_checked=result.positions_checked,
        discrepancy_count=result.discrepancy_count,
        rogue_count=result.rogue_count,
        status="COMPLETED",
    )
