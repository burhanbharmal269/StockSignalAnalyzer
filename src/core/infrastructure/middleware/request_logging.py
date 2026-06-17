"""RequestLoggingMiddleware — outermost HTTP middleware layer.

Responsibilities (in order of execution per request):
  1. Assign a correlation ID (from X-Correlation-ID header or fresh uuid4).
  2. Bind correlation_id to structlog contextvars so every log line carries it.
  3. Log the incoming request at INFO level.
  4. Delegate to the next layer via call_next().
  5. Attach X-Correlation-ID to the response headers.
  6. Log the response (status code, duration).
  7. Record Prometheus HTTP metrics.
  8. Clear structlog contextvars (always, via finally).

Register this middleware LAST so it becomes the outermost layer:
    app.add_middleware(CORSMiddleware, ...)   # inner
    app.add_middleware(RequestLoggingMiddleware)  # outermost
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.infrastructure.logging.setup import get_logger
from core.infrastructure.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)
from core.infrastructure.observability.tracing import (
    bind_structlog_context,
    clear_structlog_context,
    generate_correlation_id,
    get_correlation_id,
    set_correlation_id,
)

_CORRELATION_HEADER = "X-Correlation-ID"

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request/response and record Prometheus metrics.

    Correlation ID sourcing priority:
    1. X-Correlation-ID header from the upstream caller (gateway / LB).
    2. Freshly generated uuid4 when no header is present.

    The ID is echoed back in every response header so callers can
    correlate their logs with server logs.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = (
            request.headers.get(_CORRELATION_HEADER) or generate_correlation_id()
        )
        set_correlation_id(correlation_id)
        bind_structlog_context()

        client_host = request.client.host if request.client else "unknown"
        logger.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            client=client_host,
        )

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers[_CORRELATION_HEADER] = get_correlation_id()
            return response
        finally:
            duration = time.perf_counter() - start
            status_code = response.status_code if response is not None else 500

            logger.info(
                "http.response",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
            )
            HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                path=request.url.path,
                status=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                path=request.url.path,
            ).observe(duration)

            clear_structlog_context()
