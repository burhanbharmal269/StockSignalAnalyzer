"""Integration tests for GET /api/v1/positions endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import login_or_skip


@pytest.mark.integration
class TestPositionRouter:
    async def test_list_positions_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/positions")
        assert response.status_code == 401

    async def test_list_positions_returns_list_response(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/positions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data
        assert "total" in data
        assert isinstance(data["positions"], list)

    async def test_get_position_not_found_returns_404(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/positions/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
