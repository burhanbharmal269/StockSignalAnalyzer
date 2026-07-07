"""Tests for ResearchRegimePerformanceService — regime breakdown logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.services.research.regime_performance_service import ResearchRegimePerformanceService


def _make_service() -> ResearchRegimePerformanceService:
    sf = MagicMock()
    return ResearchRegimePerformanceService(session_factory=sf)


class TestGetRegimeBreakdown:
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_db_error(self) -> None:
        svc = _make_service()
        svc._sf = AsyncMock(side_effect=Exception("DB down"))
        result = await svc.get_regime_breakdown(lookback_days=90)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_accepts_optional_version_id(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        result = await svc.get_regime_breakdown(version_id="some-id", lookback_days=30)
        assert isinstance(result, list)


class TestComputeMethod:
    @pytest.mark.asyncio
    async def test_compute_handles_empty_results(self) -> None:
        svc = _make_service()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.execute_many = AsyncMock()
        svc._sf = MagicMock(return_value=mock_db)
        # Should not raise
        await svc.compute(lookback_days=90)
