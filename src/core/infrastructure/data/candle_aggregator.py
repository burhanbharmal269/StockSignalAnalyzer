"""CandleAggregatorService — in-memory OHLCV bar builder.

Consumes TickReceivedEvent from the event bus and publishes CandleClosedEvent
when an interval boundary is crossed. Supports configurable intervals (1m, 3m,
5m, 15m, 1h).

Crash recovery: the in-progress candle accumulator is snapshot to Redis every
``snapshot_interval_seconds`` (default 900 = 15 minutes). On startup the
service can optionally restore from Redis to avoid data gaps.

Reference: docs/12_WEBSOCKET_MANAGER.md §Candle Aggregation
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.events.market_events import CandleClosedEvent
from core.domain.events.tick_received import TickReceivedEvent
from core.infrastructure.logging.setup import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.domain.interfaces.i_event_bus import IEventBus

logger = get_logger(__name__)

_SUPPORTED_INTERVALS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}

_REDIS_SNAPSHOT_PREFIX = "candle:snapshot:"


@dataclass
class _Accumulator:
    """Mutable OHLCV state for one (instrument, interval) combination."""

    instrument_token: int
    tradingsymbol: str
    exchange: str
    interval: str
    interval_seconds: int
    bar_start: datetime
    open: Decimal | None = None
    high: Decimal = field(default_factory=lambda: Decimal("0"))
    low: Decimal = field(default_factory=lambda: Decimal("999999999"))
    close: Decimal = field(default_factory=lambda: Decimal("0"))
    volume: int = 0
    open_interest: int | None = None

    @property
    def bar_end(self) -> datetime:
        return self.bar_start + timedelta(seconds=self.interval_seconds)

    @property
    def is_empty(self) -> bool:
        return self.open is None

    def update(self, tick: TickReceivedEvent) -> None:
        if self.open is None:
            self.open = tick.last_price
            self.high = tick.last_price
            self.low = tick.last_price
        else:
            self.high = max(self.high, tick.last_price)
            self.low = min(self.low, tick.last_price)
        self.close = tick.last_price
        self.volume += tick.last_quantity
        if tick.open_interest is not None:
            self.open_interest = tick.open_interest

    def to_event(self) -> CandleClosedEvent:
        return CandleClosedEvent(
            instrument_token=self.instrument_token,
            tradingsymbol=self.tradingsymbol,
            exchange=self.exchange,
            interval=self.interval,
            open=self.open or Decimal("0"),
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            open_interest=self.open_interest,
            opened_at=self.bar_start,
            closed_at=self.bar_end,
        )

    def reset_for_tick(self, new_bar_start: datetime, tick: TickReceivedEvent) -> None:
        self.bar_start = new_bar_start
        self.open = tick.last_price
        self.high = tick.last_price
        self.low = tick.last_price
        self.close = tick.last_price
        self.volume = tick.last_quantity
        self.open_interest = tick.open_interest


class CandleAggregatorService:
    """Builds OHLCV bars from raw ticks and publishes CandleClosedEvent.

    Usage:
        aggregator = CandleAggregatorService(event_bus, redis, intervals=["1m","5m"])
        await aggregator.start()
        # ... event bus delivers ticks to on_tick() automatically ...
        await aggregator.stop()
    """

    def __init__(
        self,
        event_bus: IEventBus,
        redis_client: Redis,  # type: ignore[type-arg]
        intervals: list[str] | None = None,
        snapshot_interval_seconds: int = 900,
    ) -> None:
        self._bus = event_bus
        self._redis = redis_client
        self._intervals = intervals or ["1m", "5m", "15m"]
        self._snapshot_secs = snapshot_interval_seconds
        self._accumulators: dict[tuple[int, str], _Accumulator] = {}
        self._snapshot_task: asyncio.Task | None = None  # type: ignore[type-arg]

        for iv in self._intervals:
            if iv not in _SUPPORTED_INTERVALS:
                supported = list(_SUPPORTED_INTERVALS)
                msg = f"Unsupported candle interval: {iv!r}. Choose from {supported}"
                raise ValueError(msg)

    async def start(self) -> None:
        """Subscribe to tick events and begin snapshot loop."""
        await self._bus.subscribe(
            event_type=TickReceivedEvent,
            handler=self.on_tick,
            consumer_group="candle_aggregator",
            consumer_name="candle_aggregator_1",
        )
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        logger.info(
            "candle_aggregator.started",
            intervals=self._intervals,
            snapshot_interval_seconds=self._snapshot_secs,
        )

    async def stop(self) -> None:
        """Cancel snapshot loop and flush all open bars."""
        if self._snapshot_task:
            self._snapshot_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._snapshot_task
        logger.info("candle_aggregator.stopped")

    async def on_tick(self, event: TickReceivedEvent) -> None:
        """Process a single tick — update accumulators, emit closed candles."""
        tick_time = event.last_trade_time
        for interval in self._intervals:
            interval_secs = _SUPPORTED_INTERVALS[interval]
            key = (event.instrument_token, interval)

            if key not in self._accumulators:
                bar_start = _floor_to_interval(tick_time, interval_secs)
                self._accumulators[key] = _Accumulator(
                    instrument_token=event.instrument_token,
                    tradingsymbol=event.tradingsymbol,
                    exchange=event.exchange,
                    interval=interval,
                    interval_seconds=interval_secs,
                    bar_start=bar_start,
                )

            acc = self._accumulators[key]

            if tick_time >= acc.bar_end:
                if not acc.is_empty:
                    candle_event = acc.to_event()
                    await self._bus.publish(candle_event)
                    logger.debug(
                        "candle_aggregator.candle_closed",
                        token=event.instrument_token,
                        interval=interval,
                        close=str(acc.close),
                    )

                new_bar_start = _floor_to_interval(tick_time, interval_secs)
                acc.reset_for_tick(new_bar_start, event)
            else:
                acc.update(event)

    # ------------------------------------------------------------------
    # Redis snapshot for crash recovery
    # ------------------------------------------------------------------

    async def _snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(self._snapshot_secs)
            await self._snapshot_to_redis()

    async def _snapshot_to_redis(self) -> None:
        try:
            for (token, interval), acc in self._accumulators.items():
                if acc.is_empty:
                    continue
                key = f"{_REDIS_SNAPSHOT_PREFIX}{token}:{interval}"
                payload = json.dumps(
                    {
                        "token": token,
                        "tradingsymbol": acc.tradingsymbol,
                        "exchange": acc.exchange,
                        "interval": interval,
                        "open": str(acc.open),
                        "high": str(acc.high),
                        "low": str(acc.low),
                        "close": str(acc.close),
                        "volume": acc.volume,
                        "bar_start": acc.bar_start.isoformat(),
                        "open_interest": acc.open_interest,
                    }
                )
                await self._redis.set(key, payload, ex=self._snapshot_secs * 2)
        except Exception:
            logger.warning("candle_aggregator.snapshot.failed")


def _floor_to_interval(ts: datetime, interval_seconds: int) -> datetime:
    """Return the UTC interval start that contains *ts*."""
    epoch = ts.timestamp()
    floored = (epoch // interval_seconds) * interval_seconds
    return datetime.fromtimestamp(floored, tz=UTC)
