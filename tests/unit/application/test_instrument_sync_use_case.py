"""Unit tests for InstrumentSyncUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from core.application.use_cases.instrument_sync_use_case import InstrumentSyncUseCase
from core.domain.value_objects.instrument_refresh_result import (
    InstrumentRefreshResult,
    RefreshStatus,
)
from core.infrastructure.data.expiry_calendar import ExpiryCalendar


def _make_result(
    status: RefreshStatus = RefreshStatus.SUCCESS,
    added: int = 100,
    updated: int = 0,
    deactivated: int = 0,
    duration_ms: int = 500,
    error_detail: str = "",
) -> InstrumentRefreshResult:
    return InstrumentRefreshResult(
        status=status,
        instruments_added=added,
        instruments_updated=updated,
        instruments_deactivated=deactivated,
        duration_ms=duration_ms,
        error_detail=error_detail,
    )


def _make_use_case(
    refresh_result: InstrumentRefreshResult | None = None,
    existing_tokens: set[int] | None = None,
    raw_rows: list[dict[str, str]] | None = None,
) -> InstrumentSyncUseCase:
    master = MagicMock()
    master.refresh = AsyncMock(return_value=refresh_result or _make_result())

    provider = MagicMock()
    provider.download_instruments = AsyncMock(return_value=raw_rows or [])

    repo = MagicMock()
    repo.get_all_tokens = AsyncMock(return_value=existing_tokens or set())
    repo.save_bulk = AsyncMock()

    redis = MagicMock()
    redis.set = AsyncMock()

    calendar = ExpiryCalendar()

    return InstrumentSyncUseCase(
        instrument_master=master,
        instrument_provider=provider,
        instrument_repo=repo,
        redis_client=redis,
        expiry_calendar=calendar,
        exchanges=["NSE"],
    )


class TestExecuteFullSync:
    async def test_full_sync_delegates_to_master_refresh(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=True)
        uc._master.refresh.assert_awaited_once()

    async def test_full_sync_returns_result(self) -> None:
        result = _make_result(added=500)
        uc = _make_use_case(refresh_result=result)
        returned = await uc.execute(full=True)
        assert returned.instruments_added == 500
        assert returned.status == RefreshStatus.SUCCESS

    async def test_full_sync_stores_metadata_in_redis(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=True)
        assert uc._redis.set.await_count == 2

    async def test_full_sync_stores_success_status(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=True)
        calls = [str(c) for c in uc._redis.set.call_args_list]
        assert any("SUCCESS" in c for c in calls)

    async def test_full_sync_stores_failed_status_on_error(self) -> None:
        uc = _make_use_case()
        uc._master.refresh = AsyncMock(side_effect=RuntimeError("provider down"))
        result = await uc.execute(full=True)
        assert result.status == RefreshStatus.FAILED
        assert "provider down" in result.error_detail

    async def test_full_sync_still_stores_metadata_on_error(self) -> None:
        uc = _make_use_case()
        uc._master.refresh = AsyncMock(side_effect=RuntimeError("boom"))
        await uc.execute(full=True)
        assert uc._redis.set.await_count == 2


class TestExecuteIncrementalSync:
    async def test_incremental_skips_master_refresh(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=False)
        uc._master.refresh.assert_not_awaited()

    async def test_incremental_calls_provider_download(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=False)
        uc._provider.download_instruments.assert_awaited_once()

    async def test_incremental_upserts_only_new_tokens(self) -> None:
        existing = {1, 2, 3}
        rows = [
            {
                "instrument_token": "1",
                "tradingsymbol": "OLD",
                "exchange": "NSE",
                "name": "Old",
                "lot_size": "1",
                "tick_size": "0.05",
                "expiry": "",
                "strike": "",
                "instrument_type": "EQ",
                "segment": "NSE_EQ",
            },
            {
                "instrument_token": "99",
                "tradingsymbol": "NEW",
                "exchange": "NSE",
                "name": "New",
                "lot_size": "1",
                "tick_size": "0.05",
                "expiry": "",
                "strike": "",
                "instrument_type": "EQ",
                "segment": "NSE_EQ",
            },
        ]
        uc = _make_use_case(existing_tokens=existing, raw_rows=rows)
        result = await uc.execute(full=False)
        assert result.instruments_added == 1
        uc._repo.save_bulk.assert_awaited_once()

    async def test_incremental_returns_zero_added_when_nothing_new(self) -> None:
        existing = {1, 2, 3}
        rows = [
            {
                "instrument_token": "1",
                "tradingsymbol": "OLD",
                "exchange": "NSE",
                "name": "Old",
                "lot_size": "1",
                "tick_size": "0.05",
                "expiry": "",
                "strike": "",
                "instrument_type": "EQ",
                "segment": "NSE_EQ",
            },
        ]
        uc = _make_use_case(existing_tokens=existing, raw_rows=rows)
        result = await uc.execute(full=False)
        assert result.instruments_added == 0
        uc._repo.save_bulk.assert_not_awaited()

    async def test_incremental_skips_rows_without_token(self) -> None:
        rows = [{"tradingsymbol": "NO_TOKEN"}]
        uc = _make_use_case(existing_tokens=set(), raw_rows=rows)
        result = await uc.execute(full=False)
        assert result.instruments_added == 0

    async def test_incremental_skips_rows_with_invalid_token(self) -> None:
        rows = [{"instrument_token": "not_a_number", "tradingsymbol": "X"}]
        uc = _make_use_case(existing_tokens=set(), raw_rows=rows)
        result = await uc.execute(full=False)
        assert result.instruments_added == 0

    async def test_incremental_stores_metadata(self) -> None:
        uc = _make_use_case()
        await uc.execute(full=False)
        assert uc._redis.set.await_count == 2

    async def test_incremental_always_returns_success_status(self) -> None:
        uc = _make_use_case()
        result = await uc.execute(full=False)
        assert result.status == RefreshStatus.SUCCESS


class TestStoreMetadata:
    async def test_writes_iso_timestamp_to_redis(self) -> None:
        uc = _make_use_case()
        result = _make_result()
        await uc._store_sync_metadata(result)
        keys_written = [call.args[0] for call in uc._redis.set.call_args_list]
        assert "instrument:last_sync_at" in keys_written

    async def test_writes_status_to_redis(self) -> None:
        uc = _make_use_case()
        result = _make_result(status=RefreshStatus.PARTIAL)
        await uc._store_sync_metadata(result)
        keys_written = [call.args[0] for call in uc._redis.set.call_args_list]
        assert "instrument:sync_status" in keys_written

    async def test_does_not_raise_on_redis_error(self) -> None:
        uc = _make_use_case()
        uc._redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
        result = _make_result()
        await uc._store_sync_metadata(result)
