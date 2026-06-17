"""Unit tests for RedisUniverseRepository."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from core.domain.events.universe_events import UniverseSelected
from core.domain.universe.selected_instrument import SelectedInstrument
from core.infrastructure.cache.universe_repository import (
    RedisUniverseRepository,
    _deserialise_event,
    _serialise_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument(token: int = 1001, rank: int = 1) -> SelectedInstrument:
    return SelectedInstrument(
        instrument_token=token,
        underlying="NIFTY",
        instrument_class="OPTION",
        expiry_date=date(2026, 6, 26),
        sector="Index",
        composite_score=0.75,
        rank=rank,
        protected=False,
        filter_metadata={"stage1_eligibility": "pass"},
    )


def _make_event(*instruments: SelectedInstrument) -> UniverseSelected:
    return UniverseSelected(
        instruments=instruments,
        total_eligible=10,
        total_filtered_out=5,
        evaluation_cycle_ms=42,
        protected_count=0,
        universe_enabled=True,
    )


# ---------------------------------------------------------------------------
# Serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisationRoundTrip:
    def test_event_round_trips(self) -> None:
        inst = _make_instrument(1001, rank=1)
        original = _make_event(inst)
        payload = _serialise_event(original)
        recovered = _deserialise_event(payload)

        assert recovered.total_eligible == 10
        assert recovered.total_filtered_out == 5
        assert recovered.evaluation_cycle_ms == 42
        assert len(recovered.instruments) == 1

    def test_instrument_fields_preserved(self) -> None:
        inst = _make_instrument(1001, rank=1)
        original = _make_event(inst)
        payload = _serialise_event(original)
        recovered = _deserialise_event(payload)

        r_inst = recovered.instruments[0]
        assert r_inst.instrument_token == 1001
        assert r_inst.underlying == "NIFTY"
        assert r_inst.rank == 1
        assert r_inst.composite_score == pytest.approx(0.75)
        assert not r_inst.protected


# ---------------------------------------------------------------------------
# Redis integration (mocked)
# ---------------------------------------------------------------------------


class TestRedisUniverseRepository:
    def _make_redis(self, get_return: str | None = None) -> AsyncMock:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=get_return)
        pipe = AsyncMock()
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        pipe.set = MagicMock()
        pipe.hset = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock()
        redis.pipeline = MagicMock(return_value=pipe)
        return redis

    @pytest.mark.asyncio
    async def test_get_selected_returns_none_when_missing(self) -> None:
        redis = self._make_redis(get_return=None)
        repo = RedisUniverseRepository(redis)
        result = await repo.get_selected()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_selected_deserialises_valid_payload(self) -> None:
        inst = _make_instrument(1001)
        event = _make_event(inst)
        payload = json.dumps(_serialise_event(event))

        redis = self._make_redis(get_return=payload)
        repo = RedisUniverseRepository(redis)
        result = await repo.get_selected()

        assert result is not None
        assert result.total_eligible == 10
        assert len(result.instruments) == 1

    @pytest.mark.asyncio
    async def test_get_selected_returns_none_on_decode_error(self) -> None:
        redis = self._make_redis(get_return="not-valid-json{{{")
        repo = RedisUniverseRepository(redis)
        result = await repo.get_selected()
        assert result is None

    @pytest.mark.asyncio
    async def test_save_selected_calls_pipeline(self) -> None:
        redis = self._make_redis()
        repo = RedisUniverseRepository(redis)
        inst = _make_instrument(1001)
        event = _make_event(inst)
        await repo.save_selected(event, ttl_seconds=360)
        redis.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_selected_empty_instruments(self) -> None:
        redis = self._make_redis()
        repo = RedisUniverseRepository(redis)
        event = _make_event()
        await repo.save_selected(event, ttl_seconds=360)
        redis.pipeline.assert_called_once()
