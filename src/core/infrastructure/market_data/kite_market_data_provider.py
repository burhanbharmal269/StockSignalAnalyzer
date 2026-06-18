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

# NSE index tradingsymbol map — canonical underlying names used in F&O to Kite instrument keys.
# Kite exposes indices under NSE with their full official name, NOT the underlying abbreviation.
_INDEX_KEY_MAP: dict[str, str] = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "SENSEX":     "BSE:SENSEX",
    "BANKEX":     "BSE:BANKEX",
    "INDIA VIX":  "NSE:INDIA VIX",   # Kite key for India VIX index
}

# Kite stores index tradingsymbols with full names — map our abbreviation to Kite's name
# so _resolve_token() can find the right instrument in kite.instruments("NSE").
_INDEX_TRADINGSYMBOL_MAP: dict[str, str] = {
    "NIFTY":      "NIFTY 50",
    "BANKNIFTY":  "NIFTY BANK",
    "FINNIFTY":   "NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NIFTY MID SELECT",
    "INDIA VIX":  "INDIA VIX",
}


def _to_nse_key(symbol: str) -> str:
    """Convert an underlying symbol name to its Kite exchange:tradingsymbol key."""
    return _INDEX_KEY_MAP.get(symbol.upper(), f"NSE:{symbol}")


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
        """Fetch last traded price for a list of symbols.

        Handles both equity/index underlyings (NSE exchange) and F&O instruments.
        Index underlyings like NIFTY, BANKNIFTY, FINNIFTY are mapped to their
        correct Kite instrument key (e.g. 'NIFTY' → 'NSE:NIFTY 50').
        """
        await self._ensure_authenticated()
        loop = asyncio.get_event_loop()
        kite = self._get_kite()

        # Map canonical underlying names to Kite exchange:tradingsymbol keys.
        # Indices on NSE use their full names; equities use plain tradingsymbol.
        kite_keys = [_to_nse_key(s) for s in symbols]
        reverse: dict[str, str] = {kite_keys[i]: symbols[i] for i in range(len(symbols))}
        try:
            data: dict = await loop.run_in_executor(None, lambda: kite.ltp(kite_keys))
            return {
                reverse.get(k, k.split(":")[-1]): Decimal(str(v["last_price"]))
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

        # Must use quote() not ltp() — ltp() only returns last_price.
        # quote() returns oi, oi_day_high, oi_day_low, volume, and last_price.
        # Kite quote() limit: 500 instruments per call — batch if needed.
        quote_data: dict = {}
        try:
            for batch_start in range(0, len(syms), 500):
                batch = syms[batch_start : batch_start + 500]
                chunk: dict = await loop.run_in_executor(None, lambda b=batch: kite.quote(b))
                quote_data.update(chunk)
        except Exception as exc:
            _log.warning("kite.quote (option chain) failed: %s", exc)

        entries = []
        for inst in chain:
            key = f"NFO:{inst['tradingsymbol']}"
            quote = quote_data.get(key, {})
            oi = int(quote.get("oi", 0))
            oi_day_low = int(quote.get("oi_day_low", 0))
            # Kite has no direct oi_day_change field — approximate intraday OI change
            # as (current OI - morning OI low) which reflects net buildup since open.
            change_in_oi = max(0, oi - oi_day_low) if oi_day_low > 0 else 0
            entries.append(OptionChainEntry(
                symbol=inst["name"],
                exchange="NFO",
                expiry=inst["expiry"],
                strike=Decimal(str(inst["strike"])),
                option_type=inst["instrument_type"],
                last_price=Decimal(str(quote.get("last_price", 0))),
                open_interest=oi,
                change_in_oi=change_in_oi,
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

    async def get_quote(self, symbols: list[str], exchange: str = "NSE") -> dict[str, dict]:
        """Full quote (price + OI + volume + depth) for up to 500 instruments per call."""
        await self._ensure_authenticated()
        loop = asyncio.get_event_loop()
        kite = self._get_kite()
        keyed = [f"{exchange}:{s}" for s in symbols]
        try:
            return await loop.run_in_executor(None, lambda: kite.quote(keyed))
        except Exception as exc:
            _log.warning("kite.quote failed: %s", exc)
            return {}

    async def _resolve_token(self, symbol: str) -> int:
        if symbol in self._token_map:
            return self._token_map[symbol]
        loop = asyncio.get_event_loop()
        kite = self._get_kite()
        # Indices are stored in Kite with their full official name (e.g. "NIFTY 50"),
        # not the abbreviation used in our universe (e.g. "NIFTY").
        search_ts = _INDEX_TRADINGSYMBOL_MAP.get(symbol, symbol)
        try:
            instruments: list[dict] = await loop.run_in_executor(
                None, lambda: kite.instruments("NSE")
            )
            for inst in instruments:
                if inst["tradingsymbol"] == search_ts:
                    token = int(inst["instrument_token"])
                    self._token_map[symbol] = token
                    return token
        except Exception as exc:
            _log.warning("resolve_token failed for %s: %s", symbol, exc)
        return 0
