"""Broker router — status, trading mode, and Kite OAuth login.

GET  /api/v1/broker/status                    — broker health
GET  /api/v1/broker/mode                      — current trading mode (LIVE/PAPER)
POST /api/v1/broker/mode                      — switch trading mode at runtime (admin only)
GET  /api/v1/broker/session                   — active broker session info
GET  /api/v1/broker/login                     — Kite OAuth login URL (live mode only)
POST /api/v1/broker/callback                  — exchange Kite request_token for session
POST /api/v1/broker/kill-switch/activate      — activate the kill switch (manual only)
POST /api/v1/broker/kill-switch/deactivate    — deactivate the kill switch
"""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from container import ApplicationContainer
from core.application.services.broker.broker_health_service import BrokerHealthService
from core.application.services.kill_switch_service import KillSwitchService
from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository
from core.domain.interfaces.i_kill_switch_repository import IKillSwitchRepository
from core.infrastructure.broker.broker_session_manager import BrokerSessionManager
from core.infrastructure.config.broker_config import BrokerConfig
from core.domain.value_objects.broker_health import BrokerHealthStatus
from core.presentation.api.v1.dependencies.auth import require_admin, require_no_force_change
from core.presentation.api.v1.schemas.auth import CurrentUser
from core.presentation.api.v1.schemas.broker import (
    BrokerLoginUrlResponse,
    BrokerSessionResponse,
    BrokerSessionStatusResponse,
    BrokerStatusResponse,
    KillSwitchActivateRequest,
    KillSwitchDeactivateRequest,
    KillSwitchStateResponse,
    TradingModeResponse,
)

router = APIRouter(prefix="/api/v1/broker", tags=["Broker"])

# Redis key that stores a runtime mode override (takes precedence over env var)
_MODE_OVERRIDE_KEY = "broker:trading_mode_override"


@router.get("/status", response_model=BrokerStatusResponse, summary="Broker health and kill switch state")
@inject
async def broker_status(
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    session_repository: IBrokerSessionRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_session_repository]
    ),
    broker_health_service: BrokerHealthService = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_health_service]
    ),
    kill_switch_repository: IKillSwitchRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.kill_switch_repository]
    ),
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> BrokerStatusResponse:
    # Effective mode: Redis override takes precedence over env var
    mode_override = await redis_client.get(_MODE_OVERRIDE_KEY)
    effective_mode = (mode_override.lower() if mode_override else broker_config.trading_mode.lower())
    is_live = effective_mode == "live"
    is_paper = not is_live

    # Fetch active session (fast DB read — no Kite API call)
    broker_name_key = "kite" if is_live else "paper"
    session = await session_repository.get_active(broker_name_key)

    # Compute session status without any Kite API call
    if is_paper:
        session_status = "CONNECTED"
    elif session is None:
        session_status = "AUTH_REQUIRED"
    elif session.is_expired():
        session_status = "SESSION_EXPIRED"
    elif not session.is_active:
        session_status = "DISCONNECTED"
    else:
        session_status = "CONNECTED"

    # Health check: pass session only if live and session is valid (runs auth probe)
    health_session = (
        session
        if (is_live and session and not session.is_expired())
        else None
    )
    health = await broker_health_service.check(session=health_session)

    # Downgrade session_status only on explicit auth rejection (not connectivity/market-hours DOWN)
    if session_status == "CONNECTED" and health.details.get("auth") == "failed":
        session_status = "ERROR"

    ks_state = await kill_switch_repository.get_state()

    # Capability status derived from health probe details
    if is_paper:
        market_data_status = "OK"
        order_placement_status = "OK"
        historical_data_status = "OK"
    else:
        connectivity = health.details.get("connectivity", "failed")
        auth = health.details.get("auth", "not_checked")
        orders = health.details.get("orders", "not_checked")
        market_data_status = "OK" if connectivity == "ok" else "UNAVAILABLE"
        historical_data_status = "OK" if connectivity == "ok" else "UNAVAILABLE"
        if auth == "not_checked":
            order_placement_status = "AUTH_REQUIRED" if session_status in ("AUTH_REQUIRED", "SESSION_EXPIRED") else "UNKNOWN"
        elif auth != "ok":
            order_placement_status = "UNAVAILABLE"
        elif orders == "ok":
            order_placement_status = "OK"
        else:
            order_placement_status = "DEGRADED"

    # Use authenticated_user from session (populated at login) or from health probe
    authenticated_user = (
        health.authenticated_user
        or (session.user_name if session and session.user_name else None)
    )

    return BrokerStatusResponse(
        broker_name=health.broker_name,
        status=health.status.value,
        session_status=session_status,
        kill_switch=KillSwitchStateResponse(
            is_active=ks_state.is_active,
            activated_at=ks_state.activated_at,
            activated_by=ks_state.activated_by,
            activation_reason=ks_state.activation_reason,
            deactivated_at=ks_state.deactivated_at,
            deactivated_by=ks_state.deactivated_by,
        ),
        latency_ms=health.latency_ms,
        details=health.details,
        checked_at=health.checked_at,
        authenticated_user=authenticated_user,
        session_expires_at=session.expires_at if session else None,
        session_created_at=session.created_at if session else None,
        market_data_status=market_data_status,
        order_placement_status=order_placement_status,
        historical_data_status=historical_data_status,
    )


@router.get("/mode", response_model=TradingModeResponse, summary="Current trading mode")
@inject
async def get_trading_mode(
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> TradingModeResponse:
    # Runtime Redis override takes precedence over env var
    override = await redis_client.get(_MODE_OVERRIDE_KEY)
    mode = (override.upper() if override else broker_config.trading_mode.upper())
    return TradingModeResponse(mode=mode)


class TradingModeSwitchRequest(BaseModel):
    mode: str = Field(pattern="^(LIVE|PAPER|live|paper)$", description="Target trading mode")
    reason: str = Field(min_length=1, max_length=500, description="Reason for the mode switch")


@router.post("/mode", response_model=TradingModeResponse, summary="Switch trading mode at runtime (admin only)")
@inject
async def set_trading_mode(
    request: Request,
    user: CurrentUser = Depends(require_admin),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> TradingModeResponse:
    body = TradingModeSwitchRequest(**(await request.json()))
    new_mode = body.mode.lower()
    # Read current effective mode
    override = await redis_client.get(_MODE_OVERRIDE_KEY)
    current_mode = (override.lower() if override else broker_config.trading_mode.lower())

    if new_mode == current_mode:
        return TradingModeResponse(mode=new_mode.upper())

    # Persist override
    await redis_client.set(_MODE_OVERRIDE_KEY, new_mode)

    return TradingModeResponse(mode=new_mode.upper())


@router.get(
    "/session",
    response_model=BrokerSessionStatusResponse,
    summary="Current broker session info",
)
@inject
async def get_broker_session(
    _user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    session_repository: IBrokerSessionRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_session_repository]
    ),
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> BrokerSessionStatusResponse:
    mode_override = await redis_client.get(_MODE_OVERRIDE_KEY)
    effective_mode = (mode_override.lower() if mode_override else broker_config.trading_mode.lower())
    mode = effective_mode.upper()
    broker_name = "kite" if effective_mode == "live" else "paper"
    session = await session_repository.get_active(broker_name)

    session_resp: BrokerSessionResponse | None = None
    if session:
        session_resp = BrokerSessionResponse(
            session_id=session.session_id,
            broker_name=session.broker_name,
            is_active=session.is_active,
            is_expired=session.is_expired(),
            expires_at=session.expires_at,
            created_at=session.created_at,
            user_name=session.user_name,
        )

    return BrokerSessionStatusResponse(mode=mode, session=session_resp)


@router.get(
    "/login",
    response_model=BrokerLoginUrlResponse,
    summary="Get Kite OAuth login URL (live mode only)",
)
@inject
async def get_login_url(
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> BrokerLoginUrlResponse:
    mode_override = await redis_client.get(_MODE_OVERRIDE_KEY)
    effective_mode = (mode_override.lower() if mode_override else broker_config.trading_mode.lower())
    if effective_mode != "live":
        raise HTTPException(
            status_code=400,
            detail="Login URL is only available in LIVE trading mode.",
        )
    if not broker_config.kite_api_key:
        raise HTTPException(
            status_code=503,
            detail="KITE_API_KEY is not configured. Add it to .env and restart.",
        )
    login_url = (
        f"https://kite.zerodha.com/connect/login"
        f"?api_key={broker_config.kite_api_key}&v=3"
    )
    return BrokerLoginUrlResponse(login_url=login_url, mode="LIVE")


class KiteCallbackRequest(BaseModel):
    request_token: str


@router.get(
    "/callback",
    summary="Kite OAuth redirect handler — forwards request_token to frontend",
    include_in_schema=False,
)
async def kite_callback_redirect(
    request_token: str = Query(default=""),
    status: str = Query(default=""),
) -> RedirectResponse:
    """Zerodha redirects here after OAuth. Forward to frontend so the user can activate."""
    return RedirectResponse(
        url=f"http://localhost:3000/broker?request_token={request_token}&status={status}",
        status_code=302,
    )


@router.post(
    "/callback",
    response_model=BrokerSessionResponse,
    summary="Exchange Kite request_token for an active session",
)
@inject
async def kite_callback(
    request: Request,
    _user: CurrentUser = Depends(require_admin),  # noqa: B008
    broker_config: BrokerConfig = Depends(Provide[ApplicationContainer.broker_config]),  # noqa: B008
    session_manager: BrokerSessionManager = Depends(  # noqa: B008
        Provide[ApplicationContainer.broker_session_manager]
    ),
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
) -> BrokerSessionResponse:
    body = KiteCallbackRequest(**(await request.json()))
    mode_override = await redis_client.get(_MODE_OVERRIDE_KEY)
    effective_mode = (mode_override.lower() if mode_override else broker_config.trading_mode.lower())
    if effective_mode != "live":
        raise HTTPException(
            status_code=400,
            detail="Callback is only valid in LIVE trading mode.",
        )
    if not broker_config.kite_api_key or not broker_config.kite_api_secret:
        raise HTTPException(
            status_code=503,
            detail="KITE_API_KEY or KITE_API_SECRET is not configured.",
        )
    try:
        session = await session_manager.create_session(
            api_key=broker_config.kite_api_key,
            request_token=body.request_token,
            api_secret=broker_config.kite_api_secret,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Kite authentication failed: {exc}") from exc

    return BrokerSessionResponse(
        session_id=session.session_id,
        broker_name=session.broker_name,
        is_active=session.is_active,
        is_expired=session.is_expired(),
        expires_at=session.expires_at,
        created_at=session.created_at,
        user_name=session.user_name,
    )


@router.post(
    "/kill-switch/activate",
    response_model=KillSwitchStateResponse,
    summary="Activate the kill switch — halts all trading immediately",
)
@inject
async def activate_kill_switch(
    request: Request,
    user: CurrentUser = Depends(require_admin),  # noqa: B008
    kill_switch_service: KillSwitchService = Depends(  # noqa: B008
        Provide[ApplicationContainer.kill_switch_service]
    ),
    kill_switch_repository: IKillSwitchRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.kill_switch_repository]
    ),
) -> KillSwitchStateResponse:
    body = KillSwitchActivateRequest(**(await request.json()))
    await kill_switch_service.activate(
        reason=body.reason,
        activated_by="operator",
        trigger_source="api",
    )
    ks_state = await kill_switch_repository.get_state()
    return KillSwitchStateResponse(
        is_active=ks_state.is_active,
        activated_at=ks_state.activated_at,
        activated_by=ks_state.activated_by,
        activation_reason=ks_state.activation_reason,
        deactivated_at=ks_state.deactivated_at,
        deactivated_by=ks_state.deactivated_by,
    )


@router.post(
    "/kill-switch/deactivate",
    response_model=KillSwitchStateResponse,
    summary="Deactivate the kill switch — resumes trading",
)
@inject
async def deactivate_kill_switch(
    request: Request,
    user: CurrentUser = Depends(require_admin),  # noqa: B008
    kill_switch_service: KillSwitchService = Depends(  # noqa: B008
        Provide[ApplicationContainer.kill_switch_service]
    ),
    kill_switch_repository: IKillSwitchRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.kill_switch_repository]
    ),
) -> KillSwitchStateResponse:
    body = KillSwitchDeactivateRequest(**(await request.json()))
    await kill_switch_service.deactivate(
        deactivated_by=user.username,
        note=body.note,
        override_loss_check=body.override_loss_check,
    )
    ks_state = await kill_switch_repository.get_state()
    return KillSwitchStateResponse(
        is_active=ks_state.is_active,
        activated_at=ks_state.activated_at,
        activated_by=ks_state.activated_by,
        activation_reason=ks_state.activation_reason,
        deactivated_at=ks_state.deactivated_at,
        deactivated_by=ks_state.deactivated_by,
    )
