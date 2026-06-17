"""Health check router.

GET /api/v1/health       — liveness: process running (no downstream checks)
GET /api/v1/health/live  — alias liveness probe (k8s standard)
GET /api/v1/health/ready — readiness probe: checks Redis + DB connectivity
"""


import logging

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from container import ApplicationContainer
from core.infrastructure.config.settings import AppSettings
from core.presentation.api.v1.schemas.health import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["Health"])

_log = logging.getLogger(__name__)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
)
@inject
async def health_check(
    settings: AppSettings = Depends(Provide[ApplicationContainer.settings]),  # noqa: B008
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment.value,
        version=settings.app_version,
    )


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Kubernetes liveness probe",
)
@inject
async def liveness(
    settings: AppSettings = Depends(Provide[ApplicationContainer.settings]),  # noqa: B008
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment.value,
        version=settings.app_version,
    )


@router.get(
    "/health/ready",
    summary="Kubernetes readiness probe — checks Redis and DB",
)
@inject
async def readiness(
    settings: AppSettings = Depends(Provide[ApplicationContainer.settings]),  # noqa: B008
    redis_client: Redis = Depends(Provide[ApplicationContainer.redis_client]),  # noqa: B008
    session_factory: async_sessionmaker[AsyncSession] = Depends(  # noqa: B008
        Provide[ApplicationContainer.db_session_factory]
    ),
) -> JSONResponse:
    checks: dict[str, str] = {}
    overall_ok = True

    # Redis probe
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        _log.error("readiness.redis_failed: %s", exc)
        checks["redis"] = f"error: {exc}"
        overall_ok = False

    # DB probe
    try:
        async with session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        _log.error("readiness.db_failed: %s", exc)
        checks["database"] = f"error: {exc}"
        overall_ok = False

    http_status = 200 if overall_ok else 503
    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if overall_ok else "not_ready",
            "environment": settings.environment.value,
            "version": settings.app_version,
            "checks": checks,
        },
    )
