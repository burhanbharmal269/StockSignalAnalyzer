"""Tests for WalkForwardAnalyzerService — aggregate OOS stat computation."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.services.research.walk_forward_analyzer_service import WalkForwardAnalyzerService


def _make_service() -> WalkForwardAnalyzerService:
    sf = MagicMock()
    return WalkForwardAnalyzerService(session_factory=sf)


class TestGetAggregateOosStats:
    @pytest.mark.asyncio
    async def test_empty_windows_returns_nones(self) -> None:
        svc = _make_service()
        with patch.object(svc, "get_windows", new=AsyncMock(return_value=[])):
            result = await svc.get_aggregate_oos_stats("fake-run-id")
        assert result["window_count"] == 0
        assert result["oos_sharpe_mean"] is None

    @pytest.mark.asyncio
    async def test_single_window_no_t_stat(self) -> None:
        svc = _make_service()
        windows = [{"oos_sharpe": 1.2, "oos_win_rate": 0.6, "oos_trade_count": 20}]
        with patch.object(svc, "get_windows", new=AsyncMock(return_value=windows)):
            result = await svc.get_aggregate_oos_stats("fake-run-id")
        assert result["window_count"] == 1
        assert math.isclose(result["oos_sharpe_mean"], 1.2, abs_tol=1e-4)
        assert result["t_stat"] is None

    @pytest.mark.asyncio
    async def test_multiple_windows_computes_mean(self) -> None:
        svc = _make_service()
        windows = [
            {"oos_sharpe": 1.0, "oos_win_rate": 0.6, "oos_trade_count": 15},
            {"oos_sharpe": 1.4, "oos_win_rate": 0.65, "oos_trade_count": 18},
            {"oos_sharpe": 1.2, "oos_win_rate": 0.62, "oos_trade_count": 20},
        ]
        with patch.object(svc, "get_windows", new=AsyncMock(return_value=windows)):
            result = await svc.get_aggregate_oos_stats("fake-run-id")
        assert result["window_count"] == 3
        assert math.isclose(result["oos_sharpe_mean"], (1.0 + 1.4 + 1.2) / 3, abs_tol=1e-4)
        assert result["t_stat"] is not None
        assert 0.0 <= result["p_value"] <= 1.0

    @pytest.mark.asyncio
    async def test_windows_without_sharpe_ignored(self) -> None:
        svc = _make_service()
        windows = [
            {"oos_sharpe": None},
            {"oos_sharpe": 1.1, "oos_win_rate": 0.55, "oos_trade_count": 10},
        ]
        with patch.object(svc, "get_windows", new=AsyncMock(return_value=windows)):
            result = await svc.get_aggregate_oos_stats("fake-run-id")
        assert result["window_count"] == 1
        assert math.isclose(result["oos_sharpe_mean"], 1.1, abs_tol=1e-4)
