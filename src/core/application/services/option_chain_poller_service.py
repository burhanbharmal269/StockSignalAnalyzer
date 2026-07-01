"""OptionChainPollerService — background task that keeps option_chain_snapshots fresh.

Runs every POLL_INTERVAL_SECONDS during market hours. For each active F&O symbol
it calls OptionChainService.fetch_and_store() which fetches CE+PE quotes from
Kite and writes them to option_chain_snapshots.

The signal scanner reads from that table via OptionChainService.get_latest(), so
this poller is the data source that makes option signals possible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.application.services.market_universe_service import MarketUniverseService
    from core.application.services.option_chain_service import OptionChainService

_log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 300          # 5 minutes
_MARKET_OPEN  = (9, 15)              # (hour, minute) IST
_MARKET_CLOSE = (15, 30)
_MAX_CONCURRENT = 5                   # parallel Kite calls per batch
_BATCH_SIZE = 50                      # symbols per cycle (Kite rate-limit guard)
# Indices are always polled every cycle regardless of shuffle — their option chain
# data drives the signal engine's wall / IV / max-pain calculation.
_PRIORITY_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}


class OptionChainPollerService:
    """Continuously refreshes option chain snapshots for all active F&O stocks."""

    def __init__(
        self,
        universe_svc: "MarketUniverseService",
        option_chain_svc: "OptionChainService",
        poll_interval_seconds: int = _POLL_INTERVAL_SECONDS,
    ) -> None:
        self._universe = universe_svc
        self._option_chain = option_chain_svc
        self._interval = poll_interval_seconds

    async def run(self) -> None:
        _log.info("option_chain_poller_service.started interval_secs=%d", self._interval)
        while True:
            try:
                if self._is_market_hours():
                    await self._poll_cycle()
                else:
                    _log.debug("option_chain_poller_service.outside_market_hours — skipping")
            except Exception:
                _log.exception("option_chain_poller_service.cycle_error")
            await asyncio.sleep(self._interval)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _poll_cycle(self) -> None:
        symbols = await self._universe.get_active_symbols(fo_only=True)
        tickers = [s.symbol for s in symbols]

        # Always poll indices first (guaranteed slot), then random stock sample.
        import random
        priority = [t for t in tickers if t in _PRIORITY_SYMBOLS]
        stocks   = [t for t in tickers if t not in _PRIORITY_SYMBOLS]
        random.shuffle(stocks)
        batch = priority + stocks[:max(0, _BATCH_SIZE - len(priority))]

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        results = await asyncio.gather(
            *[self._fetch_one(t, sem) for t in batch],
            return_exceptions=True,
        )
        ok = sum(1 for r in results if r is True)
        fail = len(results) - ok
        _log.info(
            "option_chain_poller_service.cycle_done ok=%d fail=%d total=%d",
            ok, fail, len(batch),
        )

    async def _fetch_one(self, ticker: str, sem: asyncio.Semaphore) -> bool:
        async with sem:
            try:
                data = await self._option_chain.fetch_and_store(ticker)
                if "error" in data:
                    _log.debug(
                        "option_chain_poller_service.no_data symbol=%s", ticker
                    )
                    return False
                _log.debug(
                    "option_chain_poller_service.fetched symbol=%s pcr=%.2f",
                    ticker, data.get("pcr", 0),
                )
                return True
            except Exception as exc:
                _log.debug(
                    "option_chain_poller_service.fetch_failed symbol=%s err=%s",
                    ticker, exc,
                )
                return False

    @staticmethod
    def _is_market_hours() -> bool:
        now = datetime.now(UTC)
        # Convert to IST (UTC+5:30)
        ist_hour   = (now.hour + 5) % 24
        ist_minute = (now.minute + 30) % 60
        if now.minute + 30 >= 60:
            ist_hour = (ist_hour + 1) % 24
        # IST date: advance day if UTC+5:30 rolled past midnight
        ist_day = now.weekday()
        if now.hour + 5 >= 24 or (now.hour + 5 == 23 and now.minute + 30 >= 60):
            ist_day = (ist_day + 1) % 7
        if ist_day >= 5:  # Saturday=5, Sunday=6
            return False
        open_mins  = _MARKET_OPEN[0]  * 60 + _MARKET_OPEN[1]
        close_mins = _MARKET_CLOSE[0] * 60 + _MARKET_CLOSE[1]
        current    = ist_hour * 60 + ist_minute
        return open_mins <= current <= close_mins
