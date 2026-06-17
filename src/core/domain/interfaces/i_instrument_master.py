"""IInstrumentMasterService — domain port for instrument registry queries.

Reference: docs/13_INSTRUMENT_MASTER.md §Instrument Master Service Interface
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from core.domain.entities.instrument import Instrument
from core.domain.enums.option_type import OptionType
from core.domain.enums.segment import Segment
from core.domain.value_objects.instrument_refresh_result import InstrumentRefreshResult


class IInstrumentMasterService(ABC):
    """Broker-agnostic instrument registry.

    All symbol lookups, expiry queries, and lot size lookups must go through
    this service — never from hardcoded values or environment variables.
    """

    @abstractmethod
    async def get_by_token(self, token: int) -> Instrument:
        """Return instrument by broker instrument token.

        Raises:
            KeyError: If the token is not found.
        """

    @abstractmethod
    async def get_by_symbol(self, exchange: str, tradingsymbol: str) -> Instrument:
        """Return instrument by exchange and trading symbol (case-insensitive).

        Raises:
            KeyError: If the instrument is not found.
        """

    @abstractmethod
    async def find_option(
        self,
        underlying: str,
        expiry: date,
        strike: Decimal,
        option_type: OptionType,
    ) -> Instrument:
        """Return a specific option contract.

        Raises:
            KeyError: If no matching instrument is found.
        """

    @abstractmethod
    async def get_option_chain(self, underlying: str, expiry: date) -> list[Instrument]:
        """Return all active CE and PE contracts for the given underlying and expiry."""

    @abstractmethod
    async def get_all_expiries(self, underlying: str, segment: Segment) -> list[date]:
        """Return all active expiry dates for an underlying sorted ascending."""

    @abstractmethod
    async def get_next_expiry(self, underlying: str, segment: Segment) -> date:
        """Return the nearest upcoming expiry date.

        Raises:
            ValueError: If no active expiry exists for the underlying.
        """

    @abstractmethod
    async def get_monthly_expiry(
        self, underlying: str, segment: Segment, month: date
    ) -> date:
        """Return the monthly expiry date for a given month.

        Args:
            month: Any date within the target month.

        Raises:
            ValueError: If no monthly expiry exists for that month.
        """

    @abstractmethod
    async def get_lot_size(self, underlying: str, segment: Segment) -> int:
        """Return the current lot size for an underlying in a segment.

        Raises:
            KeyError: If the underlying is not found.
        """

    @abstractmethod
    async def get_atm_strike(
        self, underlying: str, expiry: date, ltp: Decimal
    ) -> Decimal:
        """Return the ATM (at-the-money) strike nearest to ltp.

        Raises:
            ValueError: If no instruments exist for the underlying and expiry.
        """

    @abstractmethod
    async def get_strike_interval(self, underlying: str) -> Decimal:
        """Return the minimum strike gap for an underlying (e.g. 50 for NIFTY).

        Raises:
            KeyError: If the underlying is not found.
        """

    @abstractmethod
    def is_trading_day(self, check_date: date) -> bool:
        """Return True if the date is a trading day (not weekend or holiday)."""

    @abstractmethod
    def get_dte(self, instrument: Instrument) -> int:
        """Return days-to-expiry for a derivative instrument.

        Returns 0 for instruments with no expiry date.
        """

    @abstractmethod
    async def refresh(self) -> InstrumentRefreshResult:
        """Execute the full daily instrument master refresh cycle.

        Downloads, validates, diffs, upserts, rebuilds cache, and publishes
        the InstrumentMasterRefreshed event.

        Returns:
            InstrumentRefreshResult with counts and status.
        """
