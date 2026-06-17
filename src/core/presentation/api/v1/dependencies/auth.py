"""JWT authentication dependency for FastAPI routes.

Usage on protected routes:
    @router.get("/protected")
    async def handler(user: CurrentUser = Depends(get_current_user)) -> ...:
        ...

Usage with admin-role guard:
    @router.post("/admin-action")
    async def handler(user: CurrentUser = Depends(require_admin)) -> ...:
        ...

The PASSWORD_CHANGE_REQUIRED gate blocks all routes except
POST /api/v1/auth/change-password when force_change=True.
"""

from __future__ import annotations

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from container import ApplicationContainer
from core.infrastructure.auth.jwt_service import JWTService, TokenError
from core.presentation.api.v1.schemas.auth import CurrentUser

_bearer = HTTPBearer(auto_error=True)

_CHANGE_PASSWORD_PATH = "/api/v1/auth/change-password"  # noqa: S105


@inject
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),  # noqa: B008
    jwt_service: JWTService = Depends(Provide[ApplicationContainer.jwt_service]),  # noqa: B008
) -> CurrentUser:
    """Validate Bearer token and return the authenticated user principal.

    Raises 401 if the token is missing, malformed, expired, or revoked.
    Raises 403 with PASSWORD_CHANGE_REQUIRED if force_change=True.
    """
    token = credentials.credentials
    try:
        claims = jwt_service.decode_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    jti: str = claims.get("jti", "")
    if jti and await jwt_service.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    force_change: bool = bool(claims.get("force_change", False))
    return CurrentUser(
        user_id=claims["sub"],
        username=claims.get("username", ""),
        role=claims.get("role", "VIEWER"),
        force_change=force_change,
        jti=claims.get("jti", ""),
        token_exp=float(claims.get("exp", 0)),
    )


async def require_no_force_change(
    user: CurrentUser = Depends(get_current_user),  # noqa: B008
) -> CurrentUser:
    """Block access when force_change=True (password must be changed first)."""
    if user.force_change:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PASSWORD_CHANGE_REQUIRED",
            headers={"X-Redirect": _CHANGE_PASSWORD_PATH},
        )
    return user


async def require_admin(
    user: CurrentUser = Depends(require_no_force_change),  # noqa: B008
) -> CurrentUser:
    """Require ADMIN role; raises 403 otherwise."""
    if user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return user


# Alias used by new routers (Phase 19+)
require_authenticated = require_no_force_change

__all__ = [
    "get_current_user",
    "require_no_force_change",
    "require_authenticated",
    "require_admin",
]
