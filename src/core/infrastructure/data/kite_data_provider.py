"""KiteInstrumentProvider — downloads instrument master CSVs from Kite Connect.

Implements IInstrumentProvider. Uses httpx for async HTTP.
No Kite-specific symbols leak into the domain layer.

Reference: docs/13_INSTRUMENT_MASTER.md §Refresh Lifecycle
"""

from __future__ import annotations

import csv
import io
from datetime import date

import httpx

from core.domain.interfaces.i_instrument_provider import IInstrumentProvider
from core.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

_KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments/{exchange}"
_KITE_HOLIDAYS_URL = "https://api.kite.trade/market/holidays/trading"
_REQUEST_TIMEOUT_SECONDS = 60
_PROVIDER_NAME = "kite"


class KiteInstrumentProvider(IInstrumentProvider):
    """Downloads instrument data from the Kite Connect REST API.

    The instruments CSV endpoint is public (no auth required).
    The holidays endpoint requires a valid access_token + api_key.
    """

    def __init__(
        self,
        access_token: str = "",
        api_key: str = "",
        timeout_seconds: int = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._access_token = access_token
        self._api_key = api_key
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return _PROVIDER_NAME

    async def download_instruments(self, exchange: str) -> list[dict[str, str]]:
        """Download and parse the Kite instrument CSV for an exchange."""
        url = _KITE_INSTRUMENTS_URL.format(exchange=exchange.upper())
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url)
            response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        logger.info(
            "kite.instruments.downloaded",
            exchange=exchange,
            row_count=len(rows),
        )
        return rows

    async def get_trading_holidays(self, exchange: str, year: int) -> list[date]:
        """Return NSE trading holidays from Kite.

        Falls back to empty list when no credentials are configured.
        """
        if not self._access_token or not self._api_key:
            logger.warning(
                "kite.holidays.skipped",
                reason="no_access_token",
                exchange=exchange,
                year=year,
            )
            return []

        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {self._api_key}:{self._access_token}",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(_KITE_HOLIDAYS_URL, headers=headers)
            response.raise_for_status()

        payload = response.json()
        exchange_key = exchange.upper()
        holidays: list[date] = []
        for entry in payload.get(exchange_key, []):
            try:
                holiday_date = date.fromisoformat(entry["date"])
                if holiday_date.year == year:
                    holidays.append(holiday_date)
            except (KeyError, ValueError):
                logger.warning(
                    "kite.holidays.parse_error",
                    entry=entry,
                    exchange=exchange,
                )
        holidays.sort()
        return holidays


# Backward-compat alias — existing references to KiteDataProvider keep working.
KiteDataProvider = KiteInstrumentProvider
