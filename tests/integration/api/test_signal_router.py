"""Integration tests for GET /api/v1/signals endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import login_or_skip


@pytest.mark.integration
class TestSignalRouter:
    async def test_list_signals_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/signals")
        assert response.status_code == 401

    async def test_list_signals_invalid_state_returns_400(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/signals?state=INVALID_STATE",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_list_signals_returns_list_response(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/signals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "signals" in data
        assert "total" in data
        assert isinstance(data["signals"], list)
        assert isinstance(data["total"], int)

    async def test_get_signal_not_found_returns_404(
        self, async_client: AsyncClient
    ) -> None:
        token = await login_or_skip(async_client)

        response = await async_client.get(
            "/api/v1/signals/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
