"""Research strategy promotion router."""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from container import ApplicationContainer
from core.presentation.api.v1.dependencies.auth import require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.research_schemas import (
    ApprovePromotionRequest,
    PromotionQueueResponse,
    RejectPromotionRequest,
    RequestPromotionRequest,
)

router = APIRouter(prefix="/api/v1/research/promotion", tags=["Research — Strategy Promotion"])


@router.get("/queue", response_model=PromotionQueueResponse, summary="Get promotion queue")
@inject
async def get_queue(
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_promotion_service]),
) -> PromotionQueueResponse:
    queue = await svc.get_queue()
    return PromotionQueueResponse(queue=queue, total=len(queue))


@router.post("/request", summary="Request promotion for a strategy version")
@inject
async def request_promotion(
    body: RequestPromotionRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_promotion_service]),
) -> dict:
    promotion_id = await svc.request_promotion(
        version_id=body.version_id,
        requested_by=body.requested_by,
    )
    return {"promotion_id": promotion_id, "status": "PENDING"}


@router.post("/{promotion_id}/approve", summary="Approve a promotion request")
@inject
async def approve_promotion(
    promotion_id: str,
    body: ApprovePromotionRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_promotion_service]),
) -> dict:
    await svc.approve(promotion_id=promotion_id, reviewer=body.reviewer)
    return {"promotion_id": promotion_id, "status": "APPROVED"}


@router.post("/{promotion_id}/reject", summary="Reject a promotion request")
@inject
async def reject_promotion(
    promotion_id: str,
    body: RejectPromotionRequest,
    _user: CurrentUser = Depends(require_no_force_change),
    svc=Depends(Provide[ApplicationContainer.research_strategy_promotion_service]),
) -> dict:
    await svc.reject(
        promotion_id=promotion_id,
        reviewer=body.reviewer,
        reason=body.reason,
    )
    return {"promotion_id": promotion_id, "status": "REJECTED"}
