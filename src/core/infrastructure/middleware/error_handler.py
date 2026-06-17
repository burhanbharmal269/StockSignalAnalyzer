"""Global unhandled-exception handler.

Catches any Exception that bubbles past all route-level handlers and returns a
structured JSON error response.

Security contract:
  - In development: the exception message is included in the response body to
    aid local debugging.
  - In staging/production: only a generic message is returned. Stack traces
    and exception details are NEVER exposed to callers outside development.
  - The full stack trace is always written to the structured log.

Register via register_error_handlers(app, is_development=settings.is_development).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from core.infrastructure.logging.setup import get_logger
from core.infrastructure.observability.tracing import get_correlation_id

logger = get_logger(__name__)


async def _handle_exception(
    request: Request,
    exc: Exception,
    is_development: bool,
) -> JSONResponse:
    """Build a structured error response for an unhandled exception."""
    correlation_id = get_correlation_id()
    logger.error(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        correlation_id=correlation_id,
        exc_info=True,
    )

    body: dict[str, str] = {
        "error": "internal_server_error",
        "correlation_id": correlation_id,
    }
    if is_development:
        body["detail"] = str(exc)

    return JSONResponse(status_code=500, content=body)


def register_error_handlers(app: FastAPI, is_development: bool) -> None:
    """Register the global exception handler on the FastAPI application.

    Args:
        app: The FastAPI instance to register handlers on.
        is_development: When True, exception detail is included in responses.
                        Pass settings.is_development at app-creation time.
    """

    def _make_handler(
        dev_mode: bool,
    ) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return await _handle_exception(request, exc, dev_mode)

        return handler

    app.add_exception_handler(Exception, _make_handler(is_development))
