"""Execution Router — runtime control of execution mode and lock state.

GET  /api/v1/execution/status       — current execution lock + mode state
POST /api/v1/execution/lock         — lock (AUTOMATIC orders blocked; signals continue)
POST /api/v1/execution/unlock       — unlock (AUTOMATIC orders allowed)
POST /api/v1/execution/mode         — change execution mode (MANUAL | AUTOMATIC)

Signal generation, storage, analytics, and outcome tracking are NEVER affected
by any endpoint here — they run regardless of lock state or execution mode.

All write operations are admin-only and create audit log entries.
"""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from container import ApplicationContainer
from core.application.services.execution_lock_service import ExecutionLockService
from core.presentation.api.v1.dependencies.auth import require_no_force_change

router = APIRouter(prefix="/api/v1/execution", tags=["Execution Control"])

_VALID_MODES = frozenset({"MANUAL", "AUTOMATIC"})


class LockRequest(BaseModel):
    note: str = ""


class ModeRequest(BaseModel):
    mode: str
    note: str = ""


def _state_to_dict(state) -> dict:
    return {
        "locked": state.locked,
        "execution_mode": state.execution_mode,
        "orders_blocked": state.is_order_blocked,
        "changed_at": state.changed_at.isoformat() if state.changed_at else None,
        "changed_by": state.changed_by,
        "note": state.note,
        "signal_generation": "ALWAYS_ON",
        "signal_analytics": "ALWAYS_ON",
        "outcome_tracking": "ALWAYS_ON",
        "market_data": "ALWAYS_LIVE",
    }


@router.get("/status", summary="Current execution lock and mode state")
@inject
async def get_execution_status(
    svc: ExecutionLockService = Depends(Provide[ApplicationContainer.execution_lock_service]),
) -> dict:
    """Returns current execution lock state and execution mode.

    orders_blocked=true  → no orders will be placed (MANUAL mode or LOCKED)
    orders_blocked=false → orders will be placed (AUTOMATIC + UNLOCKED)

    Signal generation is ALWAYS_ON regardless.
    """
    state = await svc.get_state()
    return _state_to_dict(state)


@router.post("/lock", summary="Lock order execution (admin)")
@inject
async def lock_execution(
    req: LockRequest,
    user=Depends(require_no_force_change),
    svc: ExecutionLockService = Depends(Provide[ApplicationContainer.execution_lock_service]),
) -> dict:
    """Lock order execution. Signals and analytics continue unaffected."""
    username = getattr(user, "username", "api_user")
    state = await svc.lock(locked_by=username, note=req.note or "Manually locked via API")
    return {**_state_to_dict(state), "action": "LOCKED"}


@router.post("/unlock", summary="Unlock order execution (admin)")
@inject
async def unlock_execution(
    req: LockRequest,
    user=Depends(require_no_force_change),
    svc: ExecutionLockService = Depends(Provide[ApplicationContainer.execution_lock_service]),
) -> dict:
    """Unlock order execution. Orders will be placed when mode=AUTOMATIC."""
    username = getattr(user, "username", "api_user")
    state = await svc.unlock(unlocked_by=username, note=req.note or "Manually unlocked via API")
    return {**_state_to_dict(state), "action": "UNLOCKED"}


@router.post("/mode", summary="Change execution mode (admin)")
@inject
async def set_execution_mode(
    req: ModeRequest,
    user=Depends(require_no_force_change),
    svc: ExecutionLockService = Depends(Provide[ApplicationContainer.execution_lock_service]),
) -> dict:
    """Change execution mode.

    MANUAL    — signals generated and stored, NO orders placed
    AUTOMATIC — signals generated and stored, orders routed to broker (when UNLOCKED)
    """
    mode = req.mode.upper()
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid execution_mode: {req.mode!r}. Must be MANUAL or AUTOMATIC.",
        )
    username = getattr(user, "username", "api_user")
    state = await svc.set_execution_mode(mode=mode, changed_by=username)
    return {**_state_to_dict(state), "action": f"MODE_SET_{mode}"}
