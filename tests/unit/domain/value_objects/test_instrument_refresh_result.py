"""Unit tests for InstrumentRefreshResult and related value objects."""

from __future__ import annotations

from core.domain.value_objects.instrument_refresh_result import (
    InstrumentRefreshResult,
    LotSizeChange,
    RefreshStatus,
)


class TestRefreshStatus:
    def test_success_value(self) -> None:
        assert RefreshStatus.SUCCESS == "SUCCESS"

    def test_failed_value(self) -> None:
        assert RefreshStatus.FAILED == "FAILED"

    def test_partial_value(self) -> None:
        assert RefreshStatus.PARTIAL == "PARTIAL"


class TestLotSizeChange:
    def test_fields_are_accessible(self) -> None:
        change = LotSizeChange(
            token=256265,
            tradingsymbol="NIFTY",
            old_lot_size=50,
            new_lot_size=75,
        )
        assert change.token == 256265
        assert change.old_lot_size == 50
        assert change.new_lot_size == 75

    def test_immutable(self) -> None:
        change = LotSizeChange(token=1, tradingsymbol="X", old_lot_size=1, new_lot_size=2)
        try:
            change.token = 999  # type: ignore[misc]
        except Exception:
            pass
        assert change.token == 1


class TestInstrumentRefreshResult:
    def test_success_result(self) -> None:
        result = InstrumentRefreshResult(
            status=RefreshStatus.SUCCESS,
            instruments_added=500,
            instruments_updated=1000,
            instruments_deactivated=10,
            duration_ms=1500,
        )
        assert result.status == RefreshStatus.SUCCESS
        assert result.total_processed == 1500
        assert result.has_lot_size_changes is False

    def test_partial_with_lot_changes(self) -> None:
        changes = [LotSizeChange(token=1, tradingsymbol="X", old_lot_size=50, new_lot_size=75)]
        result = InstrumentRefreshResult(
            status=RefreshStatus.PARTIAL,
            instruments_added=100,
            instruments_updated=200,
            instruments_deactivated=0,
            duration_ms=800,
            lot_size_changes=changes,
        )
        assert result.has_lot_size_changes is True
        assert len(result.lot_size_changes) == 1

    def test_failed_result_has_error_detail(self) -> None:
        result = InstrumentRefreshResult(
            status=RefreshStatus.FAILED,
            instruments_added=0,
            instruments_updated=0,
            instruments_deactivated=0,
            duration_ms=50,
            error_detail="Network timeout",
        )
        assert result.error_detail == "Network timeout"
        assert result.status == RefreshStatus.FAILED

    def test_total_processed_sum(self) -> None:
        result = InstrumentRefreshResult(
            status=RefreshStatus.SUCCESS,
            instruments_added=300,
            instruments_updated=700,
            instruments_deactivated=5,
            duration_ms=2000,
        )
        assert result.total_processed == 1000

    def test_immutable(self) -> None:
        result = InstrumentRefreshResult(
            status=RefreshStatus.SUCCESS,
            instruments_added=1,
            instruments_updated=2,
            instruments_deactivated=3,
            duration_ms=100,
        )
        try:
            result.instruments_added = 999  # type: ignore[misc]
        except Exception:
            pass
        assert result.instruments_added == 1
