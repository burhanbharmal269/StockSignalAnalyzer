"""Unit tests for ApiRateLimiterMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.infrastructure.middleware.api_rate_limiter import ApiRateLimiterMiddleware


def _make_redis(current_count: int = 0, raise_error: bool = False):
    redis = MagicMock()
    pipeline = MagicMock()

    async def _execute():
        if raise_error:
            raise ConnectionError("Redis unavailable")
        return [None, None, current_count]

    pipeline.execute = _execute
    pipeline.zremrangebyscore = MagicMock(return_value=pipeline)
    pipeline.zadd = MagicMock(return_value=pipeline)
    pipeline.zcard = MagicMock(return_value=pipeline)
    pipeline.expire = MagicMock(return_value=pipeline)

    redis.pipeline = MagicMock(return_value=pipeline)
    return redis


def _make_app(redis, limit: int = 120, enabled: bool = True) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        ApiRateLimiterMiddleware,
        redis_client=redis,
        requests_per_minute=limit,
        enabled=enabled,
    )

    @app.get("/api/v1/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/api/v1/broker/kill-switch")
    async def sensitive_endpoint():
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health_endpoint():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_request_under_limit_passes() -> None:
    redis = _make_redis(current_count=50)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_request_over_limit_returns_429() -> None:
    redis = _make_redis(current_count=121)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


@pytest.mark.asyncio
async def test_rate_limit_headers_present_on_success() -> None:
    redis = _make_redis(current_count=50)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.headers.get("x-ratelimit-limit") == "120"
    remaining = int(resp.headers.get("x-ratelimit-remaining", "-1"))
    assert remaining >= 0


@pytest.mark.asyncio
async def test_health_endpoint_exempt_from_rate_limit() -> None:
    redis = _make_redis(current_count=999)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sensitive_path_uses_lower_limit() -> None:
    # 21 requests for a sensitive path with 20/min limit → 429
    redis = _make_redis(current_count=21)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/broker/kill-switch")
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_redis_error_fails_open() -> None:
    """When Redis errors, the middleware must fail open (allow the request)."""
    redis = _make_redis(raise_error=True)
    app = _make_app(redis, limit=120)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_disabled_middleware_allows_all() -> None:
    redis = _make_redis(current_count=9999)
    app = _make_app(redis, limit=120, enabled=False)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/test")
    assert resp.status_code == 200
