"""Unit tests for TickReceivedEvent domain event."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.domain.events.tick_received import TickReceivedEvent
from core.domain.value_objects.market_depth import DepthLevel, MarketDepth
from core.domain.value_objects.ohlc import OHLC


class TestTickReceivedEvent:
    def test_default_construction(self) -> None:
        tick = TickReceivedEvent()
        assert tick.instrument_token == 0
        assert tick.tradingsymbol == ""
        assert tick.last_price == Decimal("0")

    def test_open_interest_none_by_default(self) -> None:
        tick = TickReceivedEvent(instrument_token=256265)
        assert tick.open_interest is None

    def test_ohlc_and_depth_none_in_ltp_mode(self) -> None:
        tick = TickReceivedEvent(instrument_token=256265, last_price=Decimal("22000"))
        assert tick.ohlc is None
        assert tick.depth is None

    def test_prices_are_decimal(self) -> None:
        tick = TickReceivedEvent(
            last_price=Decimal("19500.50"),
            change=Decimal("-150.25"),
        )
        assert isinstance(tick.last_price, Decimal)
        assert isinstance(tick.change, Decimal)

    def test_with_ohlc(self) -> None:
        ohlc = OHLC(
            open=Decimal("19400"),
            high=Decimal("19600"),
            low=Decimal("19350"),
            close=Decimal("19500"),
        )
        tick = TickReceivedEvent(instrument_token=256265, ohlc=ohlc)
        assert tick.ohlc is not None
        assert tick.ohlc.high == Decimal("19600")

    def test_with_market_depth(self) -> None:
        levels = tuple(
            DepthLevel(price=Decimal(str(100 + i)), quantity=10, orders=1)
            for i in range(5)
        )
        depth = MarketDepth(buy=levels, sell=levels)
        tick = TickReceivedEvent(instrument_token=256265, depth=depth)
        assert tick.depth is not None
        assert len(tick.depth.buy) == 5

    def test_last_trade_time_is_utc_aware(self) -> None:
        tick = TickReceivedEvent()
        assert tick.last_trade_time.tzinfo is not None

    def test_immutable(self) -> None:
        import dataclasses

        import pytest
        tick = TickReceivedEvent(instrument_token=256265)
        with pytest.raises(dataclasses.FrozenInstanceError):
            tick.instrument_token = 999  # type: ignore[misc]

    def test_open_interest_set_for_fno(self) -> None:
        tick = TickReceivedEvent(instrument_token=256265, open_interest=15000)
        assert tick.open_interest == 15000

    def test_last_trade_time_explicit(self) -> None:
        ts = datetime(2026, 6, 12, 9, 30, 0, tzinfo=UTC)
        tick = TickReceivedEvent(last_trade_time=ts)
        assert tick.last_trade_time == ts
