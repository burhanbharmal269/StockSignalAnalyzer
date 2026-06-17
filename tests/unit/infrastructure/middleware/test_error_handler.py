"""Unit tests for the global error handler.

Note: Starlette's ServerErrorMiddleware always re-raises exceptions after
sending the error response (to allow servers to log and test clients to
inspect). We therefore use raise_server_exceptions=False on every ASGI
transport that hits an exception-raising route — this gives us the actual
response the handler produced rather than the re-raised exception.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from core.infrastructure.middleware.error_handler import register_error_handlers
from core.infrastructure.middleware.request_logging import RequestLoggingMiddleware

_CORRELATION_HEADER = "X-Correlation-ID"


def _make_error_app(is_development: bool) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_error_handlers(app, is_development=is_development)

    @app.get("/boom")
    async def boom_route() -> None:
        raise RuntimeError("test explosion")

    @app.get("/type-error")
    async def type_error_route() -> None:
        raise TypeError("bad type")

    @app.get("/ok")
    async def ok_route() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _transport(app: FastAPI) -> httpx.ASGITransport:
    """ASGI transport that returns the handler response even when the server
    re-raises (Starlette ServerErrorMiddleware behaviour)."""
    return httpx.ASGITransport(app=app, raise_app_exceptions=False)


class TestErrorHandlerResponse:
    async def test_unhandled_exception_returns_500(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        assert response.status_code == 500

    async def test_response_body_has_error_field(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        body = response.json()
        assert body["error"] == "internal_server_error"

    async def test_response_body_has_correlation_id(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        body = response.json()
        assert "correlation_id" in body
        assert len(body["correlation_id"]) > 0

    async def test_upstream_correlation_id_in_error_body(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get(
                "/boom", headers={_CORRELATION_HEADER: "trace-xyz-789"}
            )
        body = response.json()
        assert body["correlation_id"] == "trace-xyz-789"


class TestDevelopmentModeExposesDetail:
    async def test_detail_included_in_development(self) -> None:
        app = _make_error_app(is_development=True)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        body = response.json()
        assert "detail" in body
        assert "test explosion" in body["detail"]

    async def test_different_exception_messages_in_development(self) -> None:
        app = _make_error_app(is_development=True)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/type-error")
        body = response.json()
        assert "bad type" in body.get("detail", "")


class TestProductionModeSuppressesDetail:
    async def test_detail_not_in_production(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        body = response.json()
        assert "detail" not in body

    async def test_exception_message_not_leaked_in_production(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        assert "test explosion" not in response.text

    async def test_only_error_and_correlation_id_in_production(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/boom")
        body = response.json()
        assert set(body.keys()) == {"error", "correlation_id"}


class TestSuccessfulRequestsUnaffected:
    async def test_ok_route_still_works_with_error_handler(self) -> None:
        app = _make_error_app(is_development=False)
        async with httpx.AsyncClient(transport=_transport(app), base_url="http://test") as client:
            response = await client.get("/ok")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
