"""Unit tests for CandleAggregatorService."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.events.market_events import CandleClosedEvent
from core.domain.events.tick_received import TickReceivedEvent
from core.infrastructure.data.candle_aggregator import (
    CandleAggregatorService,
    _floor_to_interval,
)

_T0 = datetime(2024, 1, 15, 9, 15, 0, tzinfo=UTC)  # 09:15:00 UTC — 1-min boundary
_T30 = datetime(2024, 1, 15, 9, 15, 30, tzinfo=UTC)  # same bar, 30s in
_T60 = datetime(2024, 1, 15, 9, 16, 0, tzinfo=UTC)  # next 1-min bar boundary


def _make_tick(
    token: int = 256265,
    symbol: str = "NIFTY2410123000CE",
    exchange: str = "NFO",
    price: Decimal = Decimal("100"),
    qty: int = 1,
    ts: datetime = _T0,
    oi: int | None = None,
) -> TickReceivedEvent:
    return TickReceivedEvent(
        instrument_token=token,
        tradingsymbol=symbol,
        exchange=exchange,
        last_price=price,
        last_quantity=qty,
        last_trade_time=ts,
        open_interest=oi,
    )


def _make_service(intervals: list[str] | None = None) -> tuple[CandleAggregatorService, AsyncMock]:
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    redis = MagicMock()
    redis.set = AsyncMock()
    svc = CandleAggregatorService(
        event_bus=bus,
        redis_client=redis,
        intervals=intervals or ["1m"],
        snapshot_interval_seconds=900,
    )
    return svc, bus


class TestFloorToInterval:
    def test_floor_aligns_to_minute(self) -> None:
        ts = datetime(2024, 1, 15, 9, 15, 42, tzinfo=UTC)
        floored = _floor_to_interval(ts, 60)
        assert floored == datetime(2024, 1, 15, 9, 15, 0, tzinfo=UTC)

    def test_floor_at_boundary_stays(self) -> None:
        ts = datetime(2024, 1, 15, 9, 15, 0, tzinfo=UTC)
        assert _floor_to_interval(ts, 60) == ts

    def test_floor_5_minute(self) -> None:
        ts = datetime(2024, 1, 15, 9, 17, 30, tzinfo=UTC)
        floored = _floor_to_interval(ts, 300)
        assert floored == datetime(2024, 1, 15, 9, 15, 0, tzinfo=UTC)


class TestCandleAggregatorInitialization:
    def test_default_intervals_accepted(self) -> None:
        svc, _ = _make_service(intervals=["1m", "5m", "15m"])
        assert svc._intervals == ["1m", "5m", "15m"]

    def test_invalid_interval_raises(self) -> None:
        bus = MagicMock()
        redis = MagicMock()
        with pytest.raises(ValueError, match="Unsupported candle interval"):
            CandleAggregatorService(event_bus=bus, redis_client=redis, intervals=["2m"])

    async def test_start_subscribes_to_tick_events(self) -> None:
        svc, bus = _make_service()
        with patch("asyncio.create_task"):
            await svc.start()
        bus.subscribe.assert_called_once()
        call_kwargs = bus.subscribe.call_args
        assert call_kwargs.kwargs["event_type"] == TickReceivedEvent


class TestTickAccumulation:
    async def test_first_tick_opens_bar(self) -> None:
        svc, bus = _make_service()
        tick = _make_tick(price=Decimal("100"), ts=_T0)
        await svc.on_tick(tick)
        key = (256265, "1m")
        assert key in svc._accumulators
        acc = svc._accumulators[key]
        assert acc.open == Decimal("100")
        assert acc.close == Decimal("100")
        bus.publish.assert_not_called()

    async def test_second_tick_updates_high(self) -> None:
        svc, _ = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("105"), ts=_T30))
        acc = svc._accumulators[(256265, "1m")]
        assert acc.high == Decimal("105")
        assert acc.close == Decimal("105")

    async def test_lower_tick_updates_low(self) -> None:
        svc, _ = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("95"), ts=_T30))
        acc = svc._accumulators[(256265, "1m")]
        assert acc.low == Decimal("95")

    async def test_volume_accumulates(self) -> None:
        svc, _ = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), qty=10, ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("101"), qty=5, ts=_T30))
        acc = svc._accumulators[(256265, "1m")]
        assert acc.volume == 15

    async def test_open_interest_updated(self) -> None:
        svc, _ = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0, oi=1000))
        await svc.on_tick(_make_tick(price=Decimal("101"), ts=_T30, oi=1200))
        acc = svc._accumulators[(256265, "1m")]
        assert acc.open_interest == 1200


class TestCandleClose:
    async def test_candle_published_at_interval_boundary(self) -> None:
        svc, bus = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("102"), ts=_T30))
        await svc.on_tick(_make_tick(price=Decimal("105"), ts=_T60))
        bus.publish.assert_called_once()
        event: CandleClosedEvent = bus.publish.call_args.args[0]
        assert isinstance(event, CandleClosedEvent)
        assert event.open == Decimal("100")
        assert event.close == Decimal("102")
        assert event.high == Decimal("102")
        assert event.interval == "1m"

    async def test_new_bar_starts_after_close(self) -> None:
        svc, bus = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("108"), ts=_T60))
        acc = svc._accumulators[(256265, "1m")]
        assert acc.open == Decimal("108")
        assert acc.bar_start == _T60

    async def test_no_event_if_accumulator_empty_at_boundary(self) -> None:
        svc, bus = _make_service()
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T60))
        bus.publish.assert_not_called()

    async def test_multiple_intervals_track_separately(self) -> None:
        svc, bus = _make_service(intervals=["1m", "5m"])
        await svc.on_tick(_make_tick(price=Decimal("100"), ts=_T0))
        await svc.on_tick(_make_tick(price=Decimal("105"), ts=_T60))
        bus.publish.assert_called_once()
        event: CandleClosedEvent = bus.publish.call_args.args[0]
        assert event.interval == "1m"

    async def test_multiple_instruments_tracked_separately(self) -> None:
        svc, bus = _make_service()
        t1 = _make_tick(token=111, symbol="AAA", price=Decimal("100"), ts=_T0)
        t2 = _make_tick(token=222, symbol="BBB", price=Decimal("200"), ts=_T0)
        await svc.on_tick(t1)
        await svc.on_tick(t2)
        assert (111, "1m") in svc._accumulators
        assert (222, "1m") in svc._accumulators
        assert svc._accumulators[(111, "1m")].open == Decimal("100")
        assert svc._accumulators[(222, "1m")].open == Decimal("200")
