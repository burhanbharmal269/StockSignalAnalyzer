"""Unit tests for RequestLoggingMiddleware."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from core.infrastructure.middleware.request_logging import RequestLoggingMiddleware

_CORRELATION_HEADER = "X-Correlation-ID"


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ok")
    async def ok_route() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/slow")
    async def slow_route() -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    return app


@pytest.fixture()
def test_app() -> FastAPI:
    return _make_test_app()


class TestCorrelationIdAssignment:
    async def test_response_has_correlation_id_header(self, test_app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok")
        assert _CORRELATION_HEADER in response.headers

    async def test_correlation_id_is_non_empty_string(self, test_app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok")
        cid = response.headers[_CORRELATION_HEADER]
        assert len(cid) > 0

    async def test_generated_correlation_id_looks_like_uuid(self, test_app: FastAPI) -> None:
        import uuid

        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok")
        cid = response.headers[_CORRELATION_HEADER]
        parsed = uuid.UUID(cid)
        assert parsed.version == 4

    async def test_upstream_correlation_id_is_forwarded(self, test_app: FastAPI) -> None:
        upstream_id = "upstream-trace-abc123"
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/ok", headers={_CORRELATION_HEADER: upstream_id}
            )
        assert response.headers[_CORRELATION_HEADER] == upstream_id

    async def test_each_request_gets_unique_id(self, test_app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/ok")
            r2 = await client.get("/ok")
        id1 = r1.headers[_CORRELATION_HEADER]
        id2 = r2.headers[_CORRELATION_HEADER]
        assert id1 != id2

    async def test_concurrent_requests_have_independent_ids(self, test_app: FastAPI) -> None:
        """Concurrent asyncio tasks must not share correlation IDs."""
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1, r2, r3 = await asyncio.gather(
                client.get("/slow"),
                client.get("/slow"),
                client.get("/slow"),
            )
        ids = {
            r1.headers[_CORRELATION_HEADER],
            r2.headers[_CORRELATION_HEADER],
            r3.headers[_CORRELATION_HEADER],
        }
        assert len(ids) == 3  # all distinct


class TestResponseStatus:
    async def test_successful_route_returns_200(self, test_app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ok")
        assert response.status_code == 200

    async def test_unknown_route_returns_404(self, test_app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/does-not-exist")
        assert response.status_code == 404
        # Middleware must still attach the correlation ID even on 404
        assert _CORRELATION_HEADER in response.headers


class TestMetricsRecording:
    async def test_request_increments_prometheus_counter(self, test_app: FastAPI) -> None:
        from prometheus_client import REGISTRY, generate_latest

        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ok")

        output = generate_latest(REGISTRY).decode()
        assert "http_requests_total" in output

    async def test_request_records_histogram(self, test_app: FastAPI) -> None:
        from prometheus_client import REGISTRY, generate_latest

        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ok")

        output = generate_latest(REGISTRY).decode()
        assert "http_request_duration_seconds" in output
