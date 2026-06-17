"""Auth router — login, logout, refresh, change-password.

All business logic lives in the injected services; routes are intentionally thin.

POST /api/v1/auth/login           — exchange credentials for access + refresh tokens
POST /api/v1/auth/logout          — revoke the current access token
POST /api/v1/auth/refresh         — exchange a valid refresh token for a new access token
POST /api/v1/auth/change-password — change password (requires authentication)
"""

import math
from datetime import UTC, datetime

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from container import ApplicationContainer
from core.domain.interfaces.i_user_repository import IUserRepository
from core.infrastructure.auth.jwt_service import JWTService, TokenError
from core.infrastructure.auth.password_service import PasswordService
from core.infrastructure.auth.rate_limiter import LoginRateLimiter
from core.infrastructure.config.security_config import SecurityConfig
from core.infrastructure.logging.setup import get_logger
from core.presentation.api.v1.dependencies.auth import get_current_user
from core.presentation.api.v1.schemas.auth import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RefreshResponse,
)


class MeResponse(BaseModel):
    user_id: str
    username: str
    role: str

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
logger = get_logger(__name__)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Obtain access and refresh tokens",
)
@inject
async def login(
    request: Request,
    jwt_service: JWTService = Depends(Provide[ApplicationContainer.jwt_service]),  # noqa: B008
    password_service: PasswordService = Depends(  # noqa: B008
        Provide[ApplicationContainer.password_service]
    ),
    rate_limiter: LoginRateLimiter = Depends(  # noqa: B008
        Provide[ApplicationContainer.rate_limiter]
    ),
    user_repository: IUserRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.user_repository]
    ),
    security_config: SecurityConfig = Depends(Provide[ApplicationContainer.security_config]),  # noqa: B008
) -> LoginResponse:
    """Authenticate with username + password and return JWT tokens."""
    body = LoginRequest(**(await request.json()))
    client_ip = request.client.host if request.client else "unknown"

    if await rate_limiter.is_locked_out(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )

    user = await user_repository.find_by_username(body.username)
    if user is None or not password_service.verify_password(body.password, user.hashed_password):
        await rate_limiter.record_failure(client_ip)
        logger.warning("auth.login_failed", username=body.username, client_ip=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    await rate_limiter.record_success(client_ip)
    await user_repository.update_last_login(user.user_id, datetime.now(UTC))

    access_token, _ = jwt_service.create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        force_change=user.force_change,
    )
    refresh_token, _ = jwt_service.create_refresh_token(user_id=user.user_id)

    logger.info("auth.login_success", username=user.username)
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=security_config.access_token_ttl_seconds,
        force_change=user.force_change,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke the current access token",
)
@inject
async def logout(
    jwt_service: JWTService = Depends(Provide[ApplicationContainer.jwt_service]),  # noqa: B008
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> MessageResponse:
    """Add the current token's jti to the Redis revocation set."""
    if user.jti:
        remaining_ttl = math.ceil(max(0.0, user.token_exp - datetime.now(UTC).timestamp()))
        if remaining_ttl > 0:
            await jwt_service.revoke(user.jti, remaining_ttl)
    logger.info("auth.logout", user_id=user.user_id)
    return MessageResponse(message="Logged out successfully.")


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="Exchange a refresh token for a new access token",
)
@inject
async def refresh_token(
    request: Request,
    jwt_service: JWTService = Depends(Provide[ApplicationContainer.jwt_service]),  # noqa: B008
    user_repository: IUserRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.user_repository]
    ),
    security_config: SecurityConfig = Depends(Provide[ApplicationContainer.security_config]),  # noqa: B008
) -> RefreshResponse:
    """Verify the refresh token and issue a new access token."""
    body = RefreshRequest(**(await request.json()))
    try:
        claims = jwt_service.decode_token(body.refresh_token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    if claims.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a refresh token.",
        )

    jti = claims.get("jti", "")
    if jti and await jwt_service.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
        )

    user_id: str = claims["sub"]
    user = await user_repository.find_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    new_token, _ = jwt_service.create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        force_change=user.force_change,
    )
    return RefreshResponse(
        access_token=new_token,
        expires_in=security_config.access_token_ttl_seconds,
    )


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change the authenticated user's password",
)
@inject
async def change_password(
    request: Request,
    password_service: PasswordService = Depends(  # noqa: B008
        Provide[ApplicationContainer.password_service]
    ),
    user_repository: IUserRepository = Depends(  # noqa: B008
        Provide[ApplicationContainer.user_repository]
    ),
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> MessageResponse:
    """Change the user's password and clear the force_change flag."""
    body = ChangePasswordRequest(**(await request.json()))
    db_user = await user_repository.find_by_id(user.user_id)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if not password_service.verify_password(body.old_password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    new_hash = password_service.hash_password(body.new_password)
    await user_repository.update_password(
        user_id=user.user_id,
        hashed_password=new_hash,
        force_change=False,
    )

    logger.info("auth.password_changed", user_id=user.user_id)
    return MessageResponse(message="Password changed successfully.")


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the authenticated user's identity from JWT claims",
)
async def get_me(
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> MeResponse:
    """Extract user identity from the validated JWT — no DB lookup required."""
    return MeResponse(user_id=user.user_id, username=user.username, role=user.role)
