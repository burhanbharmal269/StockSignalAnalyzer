"""LiveMarketFeedService — Kite WebSocket feed for 500+ symbols.

Maintains a live tick cache in Redis. Falls back to NSE polling when
WebSocket is unavailable. Publishes ticks to event bus and WebSocket clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from core.domain.interfaces.i_market_data_provider import IMarketDataProvider
    from core.infrastructure.config.broker_config import BrokerConfig
    from core.infrastructure.broker.broker_session_manager import BrokerSessionManager
    from core.infrastructure.broker.token_encryptor import TokenEncryptor
    from core.infrastructure.database.repositories.broker_session_repository import (
        SqlAlchemyBrokerSessionRepository,
    )

_log = logging.getLogger(__name__)

_TICK_TTL = 300          # Redis key TTL seconds
_NSE_POLL_INTERVAL = 5   # seconds between NSE fallback polls
_LIVE_TICK_PREFIX = "tick:"


class LiveMarketFeedService:
    """Manages real-time market data feed via Kite WebSocket or NSE polling fallback."""

    def __init__(
        self,
        redis_client: Redis,
        kite_provider: IMarketDataProvider,
        nse_provider: IMarketDataProvider,
        broker_config: BrokerConfig,
        session_repository: SqlAlchemyBrokerSessionRepository,
        token_encryptor: TokenEncryptor,
    ) -> None:
        self._redis = redis_client
        self._kite = kite_provider
        self._nse = nse_provider
        self._config = broker_config
        self._session_repo = session_repository
        self._encryptor = token_encryptor
        self._subscribed: set[str] = set()
        self._ws_connected = False
        self._kite_ticker: Any = None
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe(self, symbols: list[str]) -> None:
        new_syms = set(symbols) - self._subscribed
        if not new_syms:
            return
        self._subscribed.update(new_syms)
        if self._ws_connected and self._kite_ticker:
            await self._ws_subscribe(list(new_syms))
        _log.info("live_feed.subscribed count=%d total=%d", len(new_syms), len(self._subscribed))

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subscribed -= set(symbols)

    # ------------------------------------------------------------------
    # WebSocket feed (Kite Ticker)
    # ------------------------------------------------------------------

    async def start_kite_ws(self) -> bool:
        """Attempt to start Kite WebSocket feed. Returns True if connected."""
        session = await self._session_repo.get_active("kite")
        if not session or session.is_expired() or not self._config.is_live_mode:
            _log.info("live_feed: no live kite session — using NSE polling fallback")
            await self._redis.set("live_feed:connected", "0")
            return False
        try:
            access_token = await self._encryptor.decrypt(session.encrypted_access_token)
        except Exception as exc:
            _log.warning("live_feed: access token decrypt failed: %s — NSE fallback", exc)
            return False
        try:
            from kiteconnect import KiteTicker  # type: ignore[import-untyped]
            ticker = KiteTicker(
                self._config.kite_api_key,
                access_token=access_token,
            )
            ticker.on_ticks = self._on_kite_ticks
            ticker.on_connect = lambda ws, r: _log.info("kite_ticker.connected")
            ticker.on_close = lambda ws, c, m: self._on_ws_close()
            ticker.on_error = lambda ws, c, m: _log.warning("kite_ticker.error %s", m)
            self._kite_ticker = ticker
            loop = asyncio.get_event_loop()
            self._loop = loop  # captured for use in KiteTicker background-thread callbacks
            await loop.run_in_executor(None, ticker.connect, True)
            self._ws_connected = True
            await self._redis.set("live_feed:connected", "1")
            _log.info("live_feed: kite websocket started")
            return True
        except Exception as exc:
            _log.warning("kite_ticker.start failed: %s — using NSE polling", exc)
            await self._redis.set("live_feed:connected", "0")
            return False

    def _on_kite_ticks(self, ws, ticks: list[dict]) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._process_kite_ticks(ticks), self._loop)

    async def _process_kite_ticks(self, ticks: list[dict]) -> None:
        for tick in ticks:
            try:
                symbol = tick.get("tradingsymbol", "")
                ltp = Decimal(str(tick.get("last_price", 0)))
                await self._publish_tick(symbol, ltp, tick)
            except Exception:
                pass

    def _on_ws_close(self) -> None:
        self._ws_connected = False
        _log.warning("kite_ticker.closed — switching to NSE polling")
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self._redis.set("live_feed:connected", "0"), self._loop
            )
            asyncio.run_coroutine_threadsafe(self._start_polling_fallback(), self._loop)

    async def _ws_subscribe(self, symbols: list[str]) -> None:
        pass  # Token-based subscription handled internally by KiteTicker

    # ------------------------------------------------------------------
    # NSE polling fallback
    # ------------------------------------------------------------------

    async def _start_polling_fallback(self) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while self._running and not self._ws_connected:
            if self._subscribed:
                symbols = list(self._subscribed)[:50]  # NSE rate limit
                try:
                    ltps = await self._nse.get_ltp(symbols)
                    for sym, ltp in ltps.items():
                        await self._publish_tick(sym, ltp, {"last_price": float(ltp)})
                except Exception as exc:
                    _log.debug("nse_poll failed: %s", exc)
            await asyncio.sleep(_NSE_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Tick publishing
    # ------------------------------------------------------------------

    async def _publish_tick(self, symbol: str, ltp: Decimal, raw: dict) -> None:
        key = f"{_LIVE_TICK_PREFIX}{symbol}"
        now_iso = datetime.now(UTC).isoformat()
        payload = json.dumps({
            "symbol": symbol,
            "ltp": float(ltp),
            "ts": raw.get("last_trade_time", ""),
            "volume": raw.get("volume_traded", 0),
            "oi": raw.get("oi", 0),
            "bid": raw.get("depth", {}).get("buy", [{}])[0].get("price", 0),
            "ask": raw.get("depth", {}).get("sell", [{}])[0].get("price", 0),
        })
        await self._redis.set(key, payload, ex=_TICK_TTL)
        await self._redis.set("live_feed:last_tick_at", now_iso, ex=_TICK_TTL)

    async def get_ltp(self, symbol: str) -> Decimal | None:
        data = await self._redis.get(f"{_LIVE_TICK_PREFIX}{symbol}")
        if data:
            try:
                return Decimal(str(json.loads(data)["ltp"]))
            except Exception:
                pass
        return None

    async def get_snapshot(self, symbol: str) -> dict | None:
        data = await self._redis.get(f"{_LIVE_TICK_PREFIX}{symbol}")
        if data:
            try:
                return json.loads(data)
            except Exception:
                pass
        return None

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self._kite_ticker:
            try:
                self._kite_ticker.stop()
            except Exception:
                pass

    async def upgrade_to_kite_ws(self) -> bool:
        """Switch from NSE polling to Kite WebSocket after a new session is created.

        Safe to call even if already connected — returns True immediately when
        WebSocket is already up.  Stops the polling task before reconnecting so
        there is no duplicate tick source.
        """
        if self._ws_connected:
            _log.debug("live_feed.upgrade_to_kite_ws: already connected, skipping")
            return True
        _log.info("live_feed.upgrade_to_kite_ws: new Kite session detected — reconnecting")
        # Stop NSE polling before switching
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        connected = await self.start_kite_ws()
        if not connected:
            # Session disappeared between detection and connect — fall back again
            await self._start_polling_fallback()
        return connected

    async def start(self) -> None:
        connected = await self.start_kite_ws()
        if not connected:
            await self._start_polling_fallback()
