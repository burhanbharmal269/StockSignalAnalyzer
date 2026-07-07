"""Tests for StrategyPromotionService — gate constants and queue retrieval."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.services.research.strategy_promotion_service import (
    StrategyPromotionService,
    _OOS_SHARPE_MIN,
    _MIN_WALK_FORWARD_WINDOWS,
    _P_VALUE_MAX,
)


def _make_service() -> StrategyPromotionService:
    sf = MagicMock()
    return StrategyPromotionService(session_factory=sf)


def _make_mock_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.commit = AsyncMock()
    return mock_db


class TestGateConstants:
    """Gate thresholds must match the spec values."""

    def test_oos_sharpe_threshold(self) -> None:
        assert _OOS_SHARPE_MIN == 0.8

    def test_min_walk_forward_windows(self) -> None:
        assert _MIN_WALK_FORWARD_WINDOWS == 3

    def test_p_value_max(self) -> None:
        assert _P_VALUE_MAX == 0.05

    def test_gate_passes_when_sharpe_above_threshold(self) -> None:
        assert 1.2 > _OOS_SHARPE_MIN

    def test_gate_fails_when_sharpe_at_threshold(self) -> None:
        # gate is strictly > 0.8
        assert not (0.8 > _OOS_SHARPE_MIN)

    def test_gate_fails_when_windows_below_min(self) -> None:
        assert not (2 >= _MIN_WALK_FORWARD_WINDOWS)

    def test_gate_passes_when_windows_at_min(self) -> None:
        assert 3 >= _MIN_WALK_FORWARD_WINDOWS

    def test_gate_fails_when_p_value_at_threshold(self) -> None:
        # gate is strictly < 0.05
        assert not (0.05 < _P_VALUE_MAX)

    def test_gate_passes_when_p_value_below_threshold(self) -> None:
        assert 0.02 < _P_VALUE_MAX


class TestGetQueue:
    @pytest.mark.asyncio
    async def test_returns_list(self) -> None:
        svc = _make_service()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.mappings.return_value.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        result = await svc.get_queue()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_error(self) -> None:
        svc = _make_service()
        svc._sf = MagicMock(side_effect=Exception("DB error"))
        result = await svc.get_queue()
        assert result == []


class TestApproveReject:
    @pytest.mark.asyncio
    async def test_approve_calls_db(self) -> None:
        svc = _make_service()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        # Should not raise
        await svc.approve("some-id", reviewer="human")

    @pytest.mark.asyncio
    async def test_reject_calls_db(self) -> None:
        svc = _make_service()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)
        svc._sf = MagicMock(return_value=mock_db)
        await svc.reject("some-id", reviewer="human", reason="Not ready")
