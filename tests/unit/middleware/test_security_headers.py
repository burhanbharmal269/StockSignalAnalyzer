"""Unit tests for SecurityHeadersMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.infrastructure.middleware.security_headers import SecurityHeadersMiddleware


def _make_app(https_only: bool = False) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, https_only=https_only)

    @app.get("/api/v1/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/docs")
    async def docs_endpoint():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_x_content_type_options_present() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_deny() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.headers.get("x-frame-options") == "DENY"


@pytest.mark.asyncio
async def test_referrer_policy_present() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_cache_control_no_store() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert "no-store" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_server_header_removed() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert "server" not in resp.headers


@pytest.mark.asyncio
async def test_hsts_present_when_https_only() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app(https_only=True)), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    hsts = resp.headers.get("strict-transport-security", "")
    assert "max-age" in hsts


@pytest.mark.asyncio
async def test_hsts_absent_when_not_https_only() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app(https_only=False)), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert "strict-transport-security" not in resp.headers


@pytest.mark.asyncio
async def test_csp_restrictive_on_api_routes() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src" in csp
    assert "frame-ancestors" in csp


@pytest.mark.asyncio
async def test_permissions_policy_present() -> None:
    async with AsyncClient(transport=ASGITransport(_make_app()), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    pp = resp.headers.get("permissions-policy", "")
    assert "geolocation" in pp
