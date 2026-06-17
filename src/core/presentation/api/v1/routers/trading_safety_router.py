"""Live trading safety layer router.

GET  /api/v1/trading-safety/state             — current ramp-up state
GET  /api/v1/trading-safety/promotion-check   — evaluate promotion eligibility
POST /api/v1/trading-safety/promote           — promote to next stage (admin)
POST /api/v1/trading-safety/lock              — lock trading (admin)
POST /api/v1/trading-safety/unlock            — unlock trading (admin)
POST /api/v1/trading-safety/initialize        — initialize ramp-up (admin)
"""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from container import ApplicationContainer
from core.application.services.live_trading_safety_service import LiveTradingSafetyService
from core.presentation.api.v1.dependencies.auth import require_admin, require_authenticated
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1/trading-safety", tags=["Live Trading Safety"])


class RampUpStateResponse(BaseModel):
    ramp_id: int
    current_stage: int
    stage_capital: float
    effective_capital: float
    locked: bool
    lock_reason: str | None
    at_max_stage: bool
    stage_entered_at: str
    promoted_at: str | None


class PromotionEligibilityResponse(BaseModel):
    eligible: bool
    current_stage: int
    next_stage: int | None
    next_capital: float | None
    reason: str
    win_rate: float
    drawdown_pct: float
    trades_completed: int


class SafetyCheckRequest(BaseModel):
    win_rate: float
    drawdown_pct: float
    consecutive_losses: int
    broker_consecutive_failures: int


class LockRequest(BaseModel):
    reason: str


class PromoteRequest(BaseModel):
    win_rate: float
    drawdown_pct: float
    trades_completed: int
    consecutive_profitable_days: int


@router.get("/state", response_model=RampUpStateResponse, summary="Current ramp-up state")
@inject
async def get_ramp_up_state(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> RampUpStateResponse:
    state = await service.get_state()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ramp-up state not initialized. POST /api/v1/trading-safety/initialize first.",
        )
    return RampUpStateResponse(
        ramp_id=state.ramp_id,
        current_stage=state.current_stage,
        stage_capital=float(state.stage_capital),
        effective_capital=float(state.effective_capital),
        locked=state.locked,
        lock_reason=state.lock_reason,
        at_max_stage=state.at_max_stage,
        stage_entered_at=state.stage_entered_at.isoformat(),
        promoted_at=state.promoted_at.isoformat() if state.promoted_at else None,
    )


@router.get(
    "/promotion-check",
    response_model=PromotionEligibilityResponse,
    summary="Evaluate promotion eligibility",
)
@inject
async def check_promotion(
    win_rate: float = Query(ge=0.0, le=1.0),
    drawdown_pct: float = Query(ge=0.0),
    trades_completed: int = Query(ge=0),
    consecutive_profitable_days: int = Query(ge=0),
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> PromotionEligibilityResponse:
    result = await service.check_promotion_eligibility(
        win_rate, drawdown_pct, trades_completed, consecutive_profitable_days
    )
    return PromotionEligibilityResponse(
        eligible=result.eligible,
        current_stage=result.current_stage,
        next_stage=result.next_stage,
        next_capital=float(result.next_capital) if result.next_capital else None,
        reason=result.reason,
        win_rate=result.win_rate,
        drawdown_pct=result.drawdown_pct,
        trades_completed=result.trades_completed,
    )


@router.post("/promote", summary="Promote to next stage (admin)")
@inject
async def promote_stage(
    request: Request,
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> dict:
    body = PromoteRequest(**(await request.json()))
    try:
        state = await service.promote(
            body.win_rate, body.drawdown_pct,
            body.trades_completed, body.consecutive_profitable_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {
        "message": "Promoted to next stage",
        "current_stage": state.current_stage,
        "stage_capital": float(state.stage_capital),
    }


@router.post("/lock", summary="Lock live trading (admin)")
@inject
async def lock_trading(
    request: Request,
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> dict:
    body = LockRequest(**(await request.json()))
    await service.lock(body.reason)
    return {"message": "Trading locked", "reason": body.reason}


@router.post("/unlock", summary="Unlock live trading (admin)")
@inject
async def unlock_trading(
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> dict:
    await service.unlock()
    return {"message": "Trading unlocked"}


@router.post("/initialize", summary="Initialize ramp-up state (admin, idempotent)")
@inject
async def initialize_ramp_up(
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    service: LiveTradingSafetyService = Depends(  # noqa: B008
        Provide[ApplicationContainer.live_trading_safety_service]
    ),
) -> dict:
    state = await service.initialize()
    return {
        "message": "Ramp-up initialized",
        "current_stage": state.current_stage,
        "stage_capital": float(state.stage_capital),
    }
