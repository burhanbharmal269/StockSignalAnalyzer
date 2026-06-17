"""KiteMarketDataProvider — IMarketDataProvider backed by Kite Connect.

REST API for historical data; WebSocket for live ticks.
All KiteConnect SDK calls run in a thread executor (sync SDK).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, Any

from core.domain.interfaces.i_market_data_provider import IMarketDataProvider
from core.domain.entities.historical_candle import HistoricalCandle
from core.domain.value_objects.broker_dtos import OptionChainEntry

if TYPE_CHECKING:
    from core.infrastructure.config.broker_config import BrokerConfig
    from core.infrastructure.database.repositories.broker_session_repository import SqlAlchemyBrokerSessionRepository
    from core.infrastructure.broker.token_encryptor import TokenEncryptor

_log = logging.getLogger(__name__)

# Kite interval names
_TF_MAP = {
    "1m": "minute", "3m": "3minute", "5m": "5minute",
    "15m": "15minute", "30m": "30minute", "60m": "60minute",
    "D": "day", "W": "week",
}

# Kite max candles per request by interval
_MAX_DAYS = {
    "minute": 60, "3minute": 100, "5minute": 100,
    "15minute": 200, "30minute": 200, "60minute": 400, "day": 2000,
}


class KiteMarketDataProvider(IMarketDataProvider):
    """Primary market data provider using Kite Connect API."""

    def __init__(
        self,
        config: BrokerConfig,
        session_repository: SqlAlchemyBrokerSessionRepository | None = None,
        token_encryptor: TokenEncryptor | None = None,
    ) -> None:
        self._config = config
        self._session_repo = session_repository
        self._encryptor = token_encryptor
        self._kite: Any = None          # KiteConnect instance (lazy)
        self._ws: Any = None            # KiteConnect WebSocket
        self._tick_callbacks: dict[str, Callable] = {}
        self._token_map: dict[str, int] = {}  # symbol → instrument_token

    @property
    def provider_name(self) -> str:
        return "kite"

    def _get_kite(self) -> Any:
        if self._kite is None:
            try:
                from kiteconnect import KiteConnect  # type: ignore[import-untyped]
                self._kite = KiteConnect(api_key=self._config.kite_api_key)
            except ImportError as exc:
                msg = "kiteconnect package required for KiteMarketDataProvider"
                raise ImportError(msg) from exc
        return self._kite

    def set_access_token(self, token: str) -> None:
        self._get_kite().set_access_token(token)

    async def _ensure_authenticated(self) -> bool:
        """Load active Kite session and set access token. Returns True if authenticated."""
        if not self._session_repo or not self._encryptor:
            return False
        try:
            session = await self._session_repo.get_active("kite")
            if not session or session.is_expired():
                return False
            access_token = await self._encryptor.decrypt(session.encrypted_access_token)
            self._get_kite().set_access_token(access_token)
            return True
        except Exception as exc:
            _log.warning("kite_provider.auth_failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]:
        await self._ensure_authenticated()
        kite_interval = _TF_MAP.get(timeframe, "day")
        token = await self._resolve_token(symbol)
        loop = asyncio.get_event_loop()

        all_candles: list[HistoricalCandle] = []
        chunk_days = _MAX_DAYS.get(kite_interval, 60)
        cursor = from_dt

        while cursor < to_dt:
            chunk_end = min(cursor + timedelta(days=chunk_days), to_dt)
            try:
                raw: list[dict] = await loop.run_in_executor(
                    None,
                    lambda c=cursor, ce=chunk_end: self._get_kite().historical_data(
                        token, c, ce, kite_interval, oi=True
                    ),
                )
                for r in raw:
                    all_candles.append(HistoricalCandle(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=r["date"],
                        open=Decimal(str(r["open"])),
                        high=Decimal(str(r["high"])),
                        low=Decimal(str(r["low"])),
                        close=Decimal(str(r["close"])),
                        volume=int(r.get("volume", 0)),
                        oi=int(r.get("oi", 0)),
                    ))
            except Exception as exc:
                _log.warning("kite.historical_data failed %s %s: %s", symbol, timeframe, exc)
                break
            cursor = chunk_end

        return all_candles

    async def get_ltp(self, symbols: list[str]) -> dict[str, Decimal]:
        await self._ensure_authenticated()
        loop = asyncio.get_event_loop()
        kite = self._get_kite()
        nse_syms = [f"NSE:{s}" for s in symbols]
        try:
            data: dict = await loop.run_in_executor(None, lambda: kite.ltp(nse_syms))
            return {
                k.replace("NSE:", ""): Decimal(str(v["last_price"]))
                for k, v in data.items()
            }
        except Exception as exc:
            _log.warning("kite.ltp failed: %s", exc)
            return {}

    async def get_option_chain(
        self,
        underlying: str,
        expiry: date | None = None,
    ) -> list[OptionChainEntry]:
        loop = asyncio.get_event_loop()
        kite = self._get_kite()
        try:
            instruments: list[dict] = await loop.run_in_executor(
                None, lambda: kite.instruments("NFO")
            )
        except Exception as exc:
            _log.warning("kite.instruments failed: %s", exc)
            return []

        chain = [
            i for i in instruments
            if i["name"] == underlying
            and i["instrument_type"] in ("CE", "PE")
            and (expiry is None or i.get("expiry") == expiry)
        ]
        if not chain:
            return []

        syms = [f"NFO:{i['tradingsymbol']}" for i in chain]
        try:
            ltp_data: dict = await loop.run_in_executor(None, lambda: kite.ltp(syms))
        except Exception:
            ltp_data = {}

        entries = []
        for inst in chain:
            key = f"NFO:{inst['tradingsymbol']}"
            quote = ltp_data.get(key, {})
            entries.append(OptionChainEntry(
                symbol=inst["name"],
                exchange="NFO",
                expiry=inst["expiry"],
                strike=Decimal(str(inst["strike"])),
                option_type=inst["instrument_type"],
                last_price=Decimal(str(quote.get("last_price", 0))),
                open_interest=int(quote.get("oi", 0)),
                change_in_oi=int(quote.get("oi_day_change", 0)),
                volume=int(quote.get("volume", 0)),
                instrument_token=int(inst["instrument_token"]),
            ))
        return entries

    # ------------------------------------------------------------------
    # Live WebSocket feed
    # ------------------------------------------------------------------

    async def subscribe_live(
        self,
        symbols: list[str],
        on_tick: Callable[[str, Decimal, dict], None],
    ) -> None:
        for s in symbols:
            self._tick_callbacks[s] = on_tick
        # WebSocket subscription is handled by LiveMarketFeedService
        # which manages the KiteTicker instance separately.
        _log.info("kite.subscribe_live registered %d symbols", len(symbols))

    async def unsubscribe_live(self, symbols: list[str]) -> None:
        for s in symbols:
            self._tick_callbacks.pop(s, None)

    async def health_check(self) -> bool:
        try:
            loop = asyncio.get_event_loop()
            kite = self._get_kite()
            await loop.run_in_executor(None, lambda: kite.instruments("NSE"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_token(self, symbol: str) -> int:
        if symbol in self._token_map:
            return self._token_map[symbol]
        loop = asyncio.get_event_loop()
        kite = self._get_kite()
        try:
            instruments: list[dict] = await loop.run_in_executor(
                None, lambda: kite.instruments("NSE")
            )
            for inst in instruments:
                if inst["tradingsymbol"] == symbol:
                    token = int(inst["instrument_token"])
                    self._token_map[symbol] = token
                    return token
        except Exception as exc:
            _log.warning("resolve_token failed for %s: %s", symbol, exc)
        return 0
