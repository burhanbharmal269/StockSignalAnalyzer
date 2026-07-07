"""NSEFallbackProvider — IMarketDataProvider backed by NSE public endpoints.

Used when Kite Connect is unavailable. Provides:
- Basic LTP via NSE quote API
- Option chain via NSE option chain API
- No historical data (returns empty — use cached candles)

NSE public API has rate limits; requests are throttled.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

import httpx

from core.domain.entities.historical_candle import HistoricalCandle
from core.domain.interfaces.i_market_data_provider import IMarketDataProvider
from core.domain.value_objects.broker_dtos import OptionChainEntry

_log = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
}
_THROTTLE_SECS = 0.5   # stay well under NSE rate limits


class NSEFallbackProvider(IMarketDataProvider):
    """Read-only fallback using NSE public endpoints."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._session_valid = False

    @property
    def provider_name(self) -> str:
        return "nse_fallback"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=_HEADERS,
                timeout=10.0,
                follow_redirects=True,
            )
        if not self._session_valid:
            # Establish session cookies so NSE doesn't 403 all requests.
            # Mark valid regardless of outcome — we don't retry on every request.
            try:
                await self._client.get(_NSE_BASE)
                _log.debug("nse_fallback: session established")
            except Exception as exc:
                _log.warning("nse_fallback: session establishment failed: %s", exc)
            self._session_valid = True
        return self._client

    async def _get(self, url: str) -> dict | None:
        client = await self._get_client()
        await asyncio.sleep(_THROTTLE_SECS)
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            _log.debug("nse_fallback GET %s failed: %s", url, exc)
            return None

    async def get_ltp(self, symbols: list[str]) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        failed: list[str] = []
        for symbol in symbols:
            data = await self._get(f"{_NSE_BASE}/api/quote-equity?symbol={symbol}")
            if data:
                try:
                    ltp = Decimal(str(data["priceInfo"]["lastPrice"]))
                    result[symbol] = ltp
                except (KeyError, TypeError):
                    failed.append(symbol)
            else:
                failed.append(symbol)
        if failed and not result:
            _log.warning(
                "nse_fallback.get_ltp: all %d symbols failed — Kite auth required for live prices",
                len(failed),
            )
        elif failed:
            _log.debug("nse_fallback.get_ltp: %d/%d symbols failed", len(failed), len(symbols))
        return result

    async def get_option_chain(
        self,
        underlying: str,
        expiry: date | None = None,
        include_futures: bool = False,
    ) -> list[OptionChainEntry]:
        data = await self._get(
            f"{_NSE_BASE}/api/option-chain-indices?symbol={underlying}"
        ) or await self._get(
            f"{_NSE_BASE}/api/option-chain-equities?symbol={underlying}"
        )
        if not data:
            return []

        entries = []
        try:
            records = data.get("records", {}).get("data", [])
            for rec in records:
                exp_str = rec.get("expiryDate", "")
                for opt_type in ("CE", "PE"):
                    d = rec.get(opt_type)
                    if not d:
                        continue
                    try:
                        exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                    except ValueError:
                        exp_date = date.today()
                    if expiry and exp_date != expiry:
                        continue
                    entries.append(OptionChainEntry(
                        symbol=underlying,
                        exchange="NFO",
                        expiry=exp_date,
                        strike=Decimal(str(d.get("strikePrice", 0))),
                        option_type=opt_type,
                        last_price=Decimal(str(d.get("lastPrice", 0))),
                        open_interest=int(d.get("openInterest", 0)),
                        change_in_oi=int(d.get("changeinOpenInterest", 0)),
                        volume=int(d.get("totalTradedVolume", 0)),
                        instrument_token=0,
                    ))
        except Exception as exc:
            _log.warning("nse option_chain parse failed for %s: %s", underlying, exc)
        return entries

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[HistoricalCandle]:
        _log.debug("nse_fallback: no historical data for %s", symbol)
        return []

    async def subscribe_live(
        self,
        symbols: list[str],
        on_tick: Callable[[str, Decimal, dict], None],
    ) -> None:
        _log.warning("nse_fallback: live subscription not supported")

    async def unsubscribe_live(self, symbols: list[str]) -> None:
        pass

    async def health_check(self) -> bool:
        data = await self._get(f"{_NSE_BASE}/api/market-status")
        return data is not None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
