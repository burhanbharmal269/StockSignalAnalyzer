"""Unit tests for RedisGreeksRepository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.exceptions.risk import DataSourceUnavailableError
from core.domain.risk.greeks_snapshot import GreeksSnapshot
from core.infrastructure.cache.greeks_repository import RedisGreeksRepository

_NOW = datetime(2026, 6, 14, 9, 30, 0, tzinfo=UTC)
_FRESH_PAYLOAD = json.dumps({
    "delta": 25.0,
    "gamma": 0.5,
    "theta": -10.0,
    "vega": 500.0,
    "computed_at": _NOW.isoformat(),
})


@pytest.fixture
def redis_mock() -> AsyncMock:
    m = AsyncMock()
    pipeline_mock = AsyncMock()
    pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock)
    pipeline_mock.__aexit__ = AsyncMock(return_value=None)
    pipeline_mock.set = MagicMock()
    pipeline_mock.execute = AsyncMock(return_value=[True, True])
    m.pipeline = MagicMock(return_value=pipeline_mock)
    return m


@pytest.fixture
def repo(redis_mock: AsyncMock) -> RedisGreeksRepository:
    return RedisGreeksRepository(redis_client=redis_mock, tier1_ttl_seconds=60, tier2_ttl_seconds=300)


class TestGetPortfolioGreeks:
    async def test_empty_position_list_returns_empty_dict(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        result = await repo.get_portfolio_greeks([], 120, 90)
        assert result == {}
        redis_mock.mget.assert_not_called()

    async def test_tier1_hit_returns_snapshot(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        redis_mock.mget.return_value = [_FRESH_PAYLOAD, None]
        with patch("core.infrastructure.cache.greeks_repository.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = await repo.get_portfolio_greeks(["pos1"], 120, 90)
        snap = result["pos1"]
        assert snap is not None
        assert snap.delta == pytest.approx(25.0)
        assert snap.from_fallback is False

    async def test_tier1_miss_tier2_hit_returns_fallback(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        redis_mock.mget.return_value = [None, _FRESH_PAYLOAD]
        with patch("core.infrastructure.cache.greeks_repository.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = await repo.get_portfolio_greeks(["pos1"], 120, 90)
        snap = result["pos1"]
        assert snap is not None
        assert snap.from_fallback is True

    async def test_both_miss_returns_none(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        redis_mock.mget.return_value = [None, None]
        with patch("core.infrastructure.cache.greeks_repository.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = await repo.get_portfolio_greeks(["pos1"], 120, 90)
        assert result["pos1"] is None

    async def test_stale_tier1_falls_back_to_tier2(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        stale_time = datetime(2026, 6, 14, 7, 0, 0, tzinfo=UTC)
        stale_payload = json.dumps({
            "delta": 10.0, "gamma": 0.1, "theta": -5.0, "vega": 200.0,
            "computed_at": stale_time.isoformat(),
        })
        redis_mock.mget.return_value = [stale_payload, _FRESH_PAYLOAD]
        with patch("core.infrastructure.cache.greeks_repository.datetime") as mock_dt:
            mock_dt.now.return_value = _NOW
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            result = await repo.get_portfolio_greeks(["pos1"], 60, 90)
        snap = result["pos1"]
        assert snap is not None
        assert snap.from_fallback is True

    async def test_redis_error_raises_data_source_unavailable(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError
        redis_mock.mget.side_effect = RedisConnectionError("down")
        with pytest.raises(DataSourceUnavailableError) as exc_info:
            await repo.get_portfolio_greeks(["pos1"], 120, 90)
        assert exc_info.value.source == "greeks_cache"


class TestWriteGreeks:
    async def test_writes_both_tiers_atomically(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        snapshot = GreeksSnapshot(
            position_id="pos1",
            delta=25.0,
            gamma=0.5,
            theta=-10.0,
            vega=500.0,
            computed_at=_NOW,
            from_fallback=False,
        )
        await repo.write_greeks("pos1", snapshot)
        pipeline = redis_mock.pipeline.return_value
        assert pipeline.set.call_count == 2

    async def test_pipeline_uses_transaction(
        self, repo: RedisGreeksRepository, redis_mock: AsyncMock
    ) -> None:
        snapshot = GreeksSnapshot(
            position_id="pos1",
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            computed_at=_NOW,
            from_fallback=False,
        )
        await repo.write_greeks("pos1", snapshot)
        redis_mock.pipeline.assert_called_once_with(transaction=True)
