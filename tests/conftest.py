"""Shared pytest fixtures for the entire test suite.

Fixtures here are available to all test modules without explicit import.
The async_client fixture provides an httpx.AsyncClient wired to the FastAPI
test application — use it for all integration/API tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None, None, None]:
    """Clear the settings singleton cache before and after each test.

    This guarantees that environment variable overrides inside tests take
    effect immediately rather than being shadowed by a cached instance.
    """
    from core.infrastructure.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set baseline environment variables for the test suite.

    Applied via monkeypatch so values are automatically restored after
    each test, preventing cross-test pollution.
    Tests that override these variables use their own monkeypatch calls.
    """
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("DEBUG", "false")


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Async HTTP test client for the FastAPI application.

    Usage:
        async def test_something(async_client: AsyncClient) -> None:
            response = await async_client.get("/api/v1/health")
            assert response.status_code == 200
    """
    from app import create_app

    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        yield client
