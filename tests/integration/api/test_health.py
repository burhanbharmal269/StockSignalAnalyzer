"""Integration tests for the health check endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthEndpoint:
    async def test_health_returns_200(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200

    async def test_health_status_is_ok(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "ok"

    async def test_health_returns_environment(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        data = response.json()
        assert "environment" in data
        assert data["environment"] == "development"

    async def test_health_returns_version(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        data = response.json()
        assert "version" in data
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    async def test_health_response_schema(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/health")
        data = response.json()
        required_keys = {"status", "environment", "version"}
        assert required_keys.issubset(data.keys())

    async def test_openapi_docs_accessible(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/docs")
        assert response.status_code == 200

    async def test_openapi_schema_accessible(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "StockSignalAnalyzer"
