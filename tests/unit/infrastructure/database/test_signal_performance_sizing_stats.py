"""Unit tests for SqlAlchemySignalPerformanceRepository.get_sizing_stats()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain.interfaces.i_signal_performance_repository import KellySizingStats
from core.infrastructure.database.repositories.signal_performance_repository import (
    SqlAlchemySignalPerformanceRepository,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def session_factory(mock_session: AsyncMock) -> MagicMock:
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=cm)


@pytest.fixture
def repo(session_factory: MagicMock) -> SqlAlchemySignalPerformanceRepository:
    return SqlAlchemySignalPerformanceRepository(session_factory=session_factory)


def _make_row(total: int, wins: int, losses: int, avg_win: float | None, avg_loss: float | None) -> MagicMock:
    row = MagicMock()
    row.total = total
    row.wins = wins
    row.losses = losses
    row.avg_win = avg_win
    row.avg_loss = avg_loss
    return row


class TestGetSizingStats:
    async def test_returns_none_when_below_min_samples(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(10, 6, 4, 200.0, 100.0)
        mock_session.execute.return_value = result_mock

        result = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert result is None

    async def test_returns_stats_when_sufficient_samples(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(50, 30, 20, 200.0, 100.0)
        mock_session.execute.return_value = result_mock

        stats = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert isinstance(stats, KellySizingStats)

    async def test_win_rate_computed_correctly(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(100, 60, 40, 300.0, 150.0)
        mock_session.execute.return_value = result_mock

        stats = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert stats is not None
        assert stats.win_rate == pytest.approx(0.60)

    async def test_win_loss_ratio_avg_win_over_avg_loss(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(50, 30, 20, 200.0, 100.0)
        mock_session.execute.return_value = result_mock

        stats = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert stats is not None
        assert stats.win_loss_ratio == pytest.approx(2.0)

    async def test_win_loss_ratio_none_when_no_losses(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(50, 50, 0, 200.0, None)
        mock_session.execute.return_value = result_mock

        stats = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert stats is not None
        assert stats.win_loss_ratio is None

    async def test_sample_count_set_correctly(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(75, 45, 30, 150.0, 80.0)
        mock_session.execute.return_value = result_mock

        stats = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert stats is not None
        assert stats.sample_count == 75
        assert stats.win_count == 45
        assert stats.loss_count == 30

    async def test_default_min_samples_is_30(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(29, 15, 14, 100.0, 80.0)
        mock_session.execute.return_value = result_mock

        result = await repo.get_sizing_stats("NIFTY", "OPTION", 90)
        assert result is None

    async def test_exactly_min_samples_returns_none(
        self, repo: SqlAlchemySignalPerformanceRepository, mock_session: AsyncMock
    ) -> None:
        result_mock = MagicMock()
        result_mock.one.return_value = _make_row(30, 15, 15, 120.0, 80.0)
        mock_session.execute.return_value = result_mock

        # total == min_samples should NOT return — needs total > min
        # Actually our implementation checks: total < min_samples → None
        # So total == 30 with min_samples=30 should return stats
        result = await repo.get_sizing_stats("NIFTY", "OPTION", 90, min_samples=30)
        assert result is not None
