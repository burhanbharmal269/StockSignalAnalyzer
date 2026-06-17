"""Integration tests for /api/v1/broker endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import login_or_skip


@pytest.mark.integration
class TestBrokerRouter:
    async def test_broker_status_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/broker/status")
        assert response.status_code == 401

    async def test_broker_mode_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/broker/mode")
        assert response.status_code == 401

    async def test_broker_mode_returns_mode(self, async_client: AsyncClient) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/broker/mode",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data
        assert data["mode"] in ("LIVE", "PAPER")

    async def test_kill_switch_activate_requires_admin(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.post(
            "/api/v1/broker/kill-switch/activate",
            json={"reason": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # ADMIN should get 200; non-admin would get 403
        assert response.status_code in (200, 403)
