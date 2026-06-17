"""Unit tests for InstrumentLookupUseCase."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.use_cases.instrument_lookup_use_case import InstrumentLookupUseCase
from core.domain.entities.instrument import Instrument
from core.domain.enums.asset_type import AssetType
from core.domain.value_objects.instrument_health import InstrumentHealth
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


def _make_instrument(token: int = 256265, ticker: str = "NIFTY") -> Instrument:
    import uuid

    return Instrument(
        instrument_id=uuid.uuid4(),
        token=token,
        symbol=Symbol(ticker, "NSE"),
        name=ticker,
        asset_type=AssetType.FNO,
        exchange="NSE",
        lot_size=50,
        tick_size=Price(Decimal("0.05")),
        is_active=True,
        instrument_type="FUT",
        segment="NSE_FO",
    )


def _make_use_case(
    master_instrument: Instrument | None = None,
    active_count: int = 5000,
    redis_last_sync: str | None = None,
    redis_sync_status: str | None = None,
) -> InstrumentLookupUseCase:
    master = MagicMock()
    master.get_by_token = AsyncMock(
        return_value=master_instrument or _make_instrument()
    )
    master.get_by_symbol = AsyncMock(
        return_value=master_instrument or _make_instrument()
    )

    repo = MagicMock()
    repo.count_active = AsyncMock(return_value=active_count)

    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: (
        redis_last_sync if "last_sync_at" in key else redis_sync_status
    ))

    return InstrumentLookupUseCase(
        instrument_master=master,
        instrument_repo=repo,
        redis_client=redis,
    )


class TestGetByToken:
    async def test_delegates_to_master(self) -> None:
        inst = _make_instrument(token=12345)
        uc = _make_use_case(master_instrument=inst)
        result = await uc.get_by_token(12345)
        assert result.token == 12345

    async def test_propagates_key_error_from_master(self) -> None:
        uc = _make_use_case()
        uc._master.get_by_token = AsyncMock(side_effect=KeyError(999))
        with pytest.raises(KeyError):
            await uc.get_by_token(999)

    async def test_passes_correct_token_to_master(self) -> None:
        uc = _make_use_case()
        await uc.get_by_token(42)
        uc._master.get_by_token.assert_awaited_once_with(42)


class TestGetBySymbol:
    async def test_delegates_to_master(self) -> None:
        inst = _make_instrument(ticker="RELIANCE")
        uc = _make_use_case(master_instrument=inst)
        result = await uc.get_by_symbol("NSE", "RELIANCE")
        assert result.symbol.ticker == "RELIANCE"

    async def test_propagates_key_error_from_master(self) -> None:
        uc = _make_use_case()
        uc._master.get_by_symbol = AsyncMock(side_effect=KeyError("NSE:UNKNOWN"))
        with pytest.raises(KeyError):
            await uc.get_by_symbol("NSE", "UNKNOWN")

    async def test_passes_exchange_and_symbol_to_master(self) -> None:
        uc = _make_use_case()
        await uc.get_by_symbol("BSE", "INFY")
        uc._master.get_by_symbol.assert_awaited_once_with("BSE", "INFY")


class TestCountActive:
    async def test_returns_repo_count(self) -> None:
        uc = _make_use_case(active_count=12345)
        count = await uc.count_active()
        assert count == 12345

    async def test_calls_repo_count_active(self) -> None:
        uc = _make_use_case()
        await uc.count_active()
        uc._repo.count_active.assert_awaited_once()


class TestGetHealth:
    async def test_returns_instrument_health_type(self) -> None:
        uc = _make_use_case()
        health = await uc.get_health()
        assert isinstance(health, InstrumentHealth)

    async def test_includes_active_count(self) -> None:
        uc = _make_use_case(active_count=9876)
        health = await uc.get_health()
        assert health.instrument_count == 9876

    async def test_parses_last_sync_at_from_redis(self) -> None:
        ts = "2025-06-16T07:30:00+00:00"
        uc = _make_use_case(redis_last_sync=ts)
        health = await uc.get_health()
        assert health.last_sync_at is not None
        assert health.last_sync_at.year == 2025

    async def test_sync_status_from_redis(self) -> None:
        uc = _make_use_case(redis_sync_status="SUCCESS")
        health = await uc.get_health()
        assert health.sync_status == "SUCCESS"

    async def test_defaults_when_no_redis_data(self) -> None:
        uc = _make_use_case(redis_last_sync=None, redis_sync_status=None)
        health = await uc.get_health()
        assert health.last_sync_at is None
        assert health.sync_status == "UNKNOWN"

    async def test_defaults_on_redis_failure(self) -> None:
        uc = _make_use_case()
        uc._redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        health = await uc.get_health()
        assert health.last_sync_at is None
        assert health.sync_status == "UNKNOWN"

    async def test_partial_status_preserved(self) -> None:
        uc = _make_use_case(redis_sync_status="PARTIAL")
        health = await uc.get_health()
        assert health.sync_status == "PARTIAL"

    async def test_failed_status_preserved(self) -> None:
        uc = _make_use_case(redis_sync_status="FAILED")
        health = await uc.get_health()
        assert health.sync_status == "FAILED"
