"""Shared helpers for integration API tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def login_or_skip(
    client: AsyncClient,
    username: str = "admin",
    password: str = "AdminPassword123!",
) -> str:
    """Attempt login and return the access token.

    Calls pytest.skip if the auth endpoint raises (e.g. asyncpg not installed)
    or returns a non-200 status (e.g. DB not running or creds not seeded).
    """
    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    except Exception:
        pytest.skip("Auth endpoint unavailable in this environment")

    if response.status_code != 200:
        pytest.skip("Default admin credentials not available in this environment")

    return response.json()["access_token"]
