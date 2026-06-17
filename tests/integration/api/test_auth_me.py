"""Integration tests for GET /api/v1/auth/me."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import login_or_skip


@pytest.mark.integration
class TestAuthMe:
    async def test_me_without_token_returns_401(self, async_client: AsyncClient) -> None:
        response = await async_client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_me_with_invalid_token_returns_401(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401

    async def test_me_response_schema(self, async_client: AsyncClient) -> None:
        """Verify the /me response has user_id, username, role (not email, not id)."""
        token = await login_or_skip(async_client)
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "user_id" in data
        assert "username" in data
        assert "role" in data
        assert "email" not in data
        assert "id" not in data
