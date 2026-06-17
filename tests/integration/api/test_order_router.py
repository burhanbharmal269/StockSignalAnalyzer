"""Integration tests for GET /api/v1/orders endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import login_or_skip


@pytest.mark.integration
class TestOrderRouter:
    async def test_list_orders_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/orders")
        assert response.status_code == 401

    async def test_list_orders_returns_list_response(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/orders",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        assert "total" in data
        assert isinstance(data["orders"], list)

    async def test_list_orders_invalid_state_returns_400(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/orders?state=BOGUS",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_get_order_not_found_returns_404(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/orders/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
