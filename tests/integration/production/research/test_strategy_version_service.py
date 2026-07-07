"""Tests for StrategyVersionService — V1 seeding and immutability enforcement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.services.research.strategy_version_service import StrategyVersionService


def _make_service() -> StrategyVersionService:
    sf = MagicMock()
    return StrategyVersionService(session_factory=sf)


class TestGetVersion:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        result = await svc.get_version("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        row = {"id": "abc", "name": "V1", "is_immutable": True, "weights_snapshot": {}}
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        result = await svc.get_version("abc")
        assert result is not None
        assert result["name"] == "V1"


class TestUpdateVariant:
    @pytest.mark.asyncio
    async def test_raises_on_immutable_version(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        row = {"id": "v1-id", "is_immutable": True}
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        with pytest.raises(ValueError, match="immutable"):
            await svc.update_variant("v1-id", weights={}, params={})


class TestListVersions:
    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        result = await svc.list_versions()
        assert isinstance(result, list)
