"""SecurityHeadersMiddleware — adds OWASP-recommended security headers to all responses.

Adds:
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  X-XSS-Protection: 1; mode=block
  Strict-Transport-Security: max-age=31536000; includeSubDomains (HTTPS only)
  Content-Security-Policy: default-src 'self'
  Referrer-Policy: strict-origin-when-cross-origin
  Cache-Control: no-store (for API responses)
  Permissions-Policy: geolocation=(), camera=(), microphone=()
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cache-Control": "no-store, no-cache, must-revalidate",
}

_HSTS_HEADER = "Strict-Transport-Security"
_HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"

_CSP_API = "default-src 'none'; frame-ancestors 'none'"
_CSP_DOCS = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security headers on every response."""

    def __init__(self, app, *, https_only: bool = False) -> None:
        super().__init__(app)
        self._https_only = https_only

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        if self._https_only:
            response.headers[_HSTS_HEADER] = _HSTS_VALUE

        path = request.url.path
        if path.startswith(("/docs", "/redoc", "/openapi")):
            response.headers["Content-Security-Policy"] = _CSP_DOCS
        else:
            response.headers["Content-Security-Policy"] = _CSP_API

        # Remove server fingerprinting header
        try:
            del response.headers["server"]
        except KeyError:
            pass

        return response
