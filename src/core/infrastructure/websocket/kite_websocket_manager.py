"""KiteWebSocketManager — KiteTicker adapter implementing IWebSocketManager.

Wraps the kiteconnect KiteTicker (callback-based, runs in a background thread)
and bridges it to the async IEventBus via asyncio.run_coroutine_threadsafe().

The kiteconnect package is an optional dependency. If it is not installed,
instantiating this class raises ImportError. Unit tests use InMemoryWebSocketManager
instead and do not require kiteconnect.

Reference: docs/12_WEBSOCKET_MANAGER.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.domain.enums.connection_state import ConnectionState
from core.domain.enums.subscription_mode import SubscriptionMode
from core.domain.events.tick_received import TickReceivedEvent
from core.domain.interfaces.i_event_bus import IEventBus
from core.domain.interfaces.i_websocket_manager import InstrumentToken, IWebSocketManager
from core.domain.value_objects.market_depth import DepthLevel, MarketDepth
from core.domain.value_objects.ohlc import OHLC
from core.infrastructure.websocket.connection_state_machine import ConnectionStateMachine
from core.infrastructure.websocket.reconnect_policy import ReconnectPolicy
from core.infrastructure.websocket.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)

# Kite-specific mode name mapping — never exposed outside this module.
_KITE_MODE_MAP: dict[SubscriptionMode, str] = {
    SubscriptionMode.LTP: "ltp",
    SubscriptionMode.QUOTE: "quote",
    SubscriptionMode.FULL: "full",
}

try:
    from kiteconnect import KiteTicker as _KiteTicker  # type: ignore[import-untyped]

    _KITE_AVAILABLE = True
except ImportError:
    _KiteTicker = None  # type: ignore[assignment,misc]
    _KITE_AVAILABLE = False


class KiteWebSocketManager(IWebSocketManager):
    """Production WebSocket manager backed by the Kite Connect streaming API.

    Requires:
        pip install kiteconnect

    The KiteTicker runs in a background thread (Kite's design). Ticks are
    dispatched to the async event bus via asyncio.run_coroutine_threadsafe()
    so the WebSocket read loop is never blocked by async I/O.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
        event_bus: IEventBus,
        max_reconnect_attempts: int = 5,
        max_subscriptions_per_connection: int = 3000,
    ) -> None:
        if not _KITE_AVAILABLE:
            msg = (
                "kiteconnect package is required for KiteWebSocketManager. "
                "Install with: pip install kiteconnect"
            )
            raise ImportError(msg)

        self._api_key = api_key
        self._access_token = access_token
        self._event_bus = event_bus
        self._state_machine = ConnectionStateMachine()
        self._reconnect_policy = ReconnectPolicy(max_attempts=max_reconnect_attempts)
        self._subscription_manager = SubscriptionManager(
            max_per_connection=max_subscriptions_per_connection
        )
        self._last_tick_times: dict[InstrumentToken, datetime] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ticker: Any = None  # KiteTicker instance

    # ------------------------------------------------------------------
    # IWebSocketManager
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initiate connection through the full state machine."""
        self._loop = asyncio.get_running_loop()
        self._state_machine.transition(ConnectionState.CONNECTING, reason="start() called")
        self._ticker = _KiteTicker(self._api_key, self._access_token)
        self._ticker.on_ticks = self._on_ticks
        self._ticker.on_connect = self._on_connect
        self._ticker.on_close = self._on_close
        self._ticker.on_error = self._on_error
        self._ticker.connect(threaded=True)

    async def stop(self) -> None:
        """Gracefully disconnect."""
        if self._ticker is not None:
            self._ticker.stop()
        current = self._state_machine.state
        if current not in (ConnectionState.DISCONNECTED, ConnectionState.FAILED):
            self._state_machine.transition(ConnectionState.DISCONNECTED, reason="stop() called")

    async def subscribe(
        self,
        instruments: list[InstrumentToken],
        mode: SubscriptionMode,
    ) -> None:
        """Add instruments to the subscription set and send to the broker."""
        for token in instruments:
            self._subscription_manager.add(token, mode)
        if self._ticker is not None and self._state_machine.state == ConnectionState.STREAMING:
            self._ticker.subscribe(instruments)
            self._ticker.set_mode(self._ticker.MODE_FULL, instruments)

    async def unsubscribe(self, instruments: list[InstrumentToken]) -> None:
        """Remove instruments from the subscription set."""
        for token in instruments:
            self._subscription_manager.remove(token)
        if self._ticker is not None and self._state_machine.state == ConnectionState.STREAMING:
            self._ticker.unsubscribe(instruments)

    def get_connection_state(self) -> ConnectionState:
        return self._state_machine.state

    def get_subscription_count(self) -> int:
        return self._subscription_manager.count()

    def get_last_tick_time(self, instrument: InstrumentToken) -> datetime | None:
        return self._last_tick_times.get(instrument)

    # ------------------------------------------------------------------
    # KiteTicker callbacks (run in the KiteTicker background thread)
    # ------------------------------------------------------------------

    def _on_connect(self, ws: Any, response: Any) -> None:  # noqa: ANN401
        self._state_machine.transition(
            ConnectionState.AUTHENTICATING, reason="handshake complete"
        )
        self._state_machine.transition(
            ConnectionState.CONNECTED, reason="authenticated"
        )
        active = self._subscription_manager.get_all()
        if active:
            self._state_machine.transition(ConnectionState.SUBSCRIBING, reason="re-subscribing")
            tokens = list(active.keys())
            self._ticker.subscribe(tokens)
            self._state_machine.transition(ConnectionState.STREAMING, reason="subscribed")

    def _on_ticks(self, ws: Any, ticks: list[dict[str, Any]]) -> None:  # noqa: ANN401
        if self._loop is None:
            return
        for raw in ticks:
            try:
                event = _normalize_tick(raw)
                self._last_tick_times[event.instrument_token] = event.occurred_at
                asyncio.run_coroutine_threadsafe(
                    self._event_bus.publish(event),
                    self._loop,
                )
            except Exception:  # noqa: BLE001
                logger.exception("tick_normalization_error", extra={"raw_tick": raw})

    def _on_close(self, ws: Any, code: int, reason: str) -> None:  # noqa: ANN401
        current = self._state_machine.state
        if current == ConnectionState.STREAMING:
            self._state_machine.transition(
                ConnectionState.RECONNECTING, reason=f"close code={code} {reason}"
            )

    def _on_error(self, ws: Any, code: int, reason: str) -> None:  # noqa: ANN401
        logger.error(
            "websocket_error",
            extra={"code": code, "reason": reason, "state": self._state_machine.state},
        )
        current = self._state_machine.state
        if current not in (ConnectionState.FAILED, ConnectionState.DISCONNECTED):
            self._state_machine.transition(
                ConnectionState.RECONNECTING, reason=f"error code={code}"
            )


# ------------------------------------------------------------------
# Tick normalization (pure function — no side effects)
# ------------------------------------------------------------------


def _normalize_tick(raw: dict[str, Any]) -> TickReceivedEvent:
    """Convert a raw Kite tick dict to a normalized TickReceivedEvent.

    All prices become Decimal. Timestamps convert from IST to UTC.
    open_interest is preserved as None for non-FnO instruments.
    """
    ohlc: OHLC | None = None
    if "ohlc" in raw and raw["ohlc"]:
        o = raw["ohlc"]
        ohlc = OHLC(
            open=Decimal(str(o.get("open", 0))),
            high=Decimal(str(o.get("high", 0))),
            low=Decimal(str(o.get("low", 0))),
            close=Decimal(str(o.get("close", 0))),
        )

    depth: MarketDepth | None = None
    if "depth" in raw and raw["depth"]:
        d = raw["depth"]
        buy_levels = tuple(
            DepthLevel(
                price=Decimal(str(level.get("price", 0))),
                quantity=int(level.get("quantity", 0)),
                orders=int(level.get("orders", 0)),
            )
            for level in d.get("buy", [])[:5]
        )
        sell_levels = tuple(
            DepthLevel(
                price=Decimal(str(level.get("price", 0))),
                quantity=int(level.get("quantity", 0)),
                orders=int(level.get("orders", 0)),
            )
            for level in d.get("sell", [])[:5]
        )
        depth = MarketDepth(buy=buy_levels, sell=sell_levels)

    last_trade_time_raw = raw.get("last_trade_time")
    if isinstance(last_trade_time_raw, datetime):
        last_trade_time = (
            last_trade_time_raw
            if last_trade_time_raw.tzinfo is not None
            else last_trade_time_raw.replace(tzinfo=UTC)
        )
    else:
        last_trade_time = datetime.now(UTC)

    return TickReceivedEvent(
        instrument_token=int(raw.get("instrument_token", 0)),
        tradingsymbol=str(raw.get("tradingsymbol", "")),
        exchange=str(raw.get("exchange", "")),
        last_price=Decimal(str(raw.get("last_price", 0))),
        last_quantity=int(raw.get("last_quantity", 0)),
        buy_quantity=int(raw.get("buy_quantity", 0)),
        sell_quantity=int(raw.get("sell_quantity", 0)),
        volume=int(raw.get("volume", 0)),
        open_interest=raw.get("oi"),  # None for equity — intentional
        change=Decimal(str(raw.get("change", 0))),
        last_trade_time=last_trade_time,
        ohlc=ohlc,
        depth=depth,
    )
