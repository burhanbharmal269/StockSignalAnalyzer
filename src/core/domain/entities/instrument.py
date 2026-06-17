"""Instrument entity — represents a tradeable NSE instrument.

Source of truth: docs/13_INSTRUMENT_MASTER.md
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.domain.enums.asset_type import AssetType
from core.domain.value_objects.price import Price
from core.domain.value_objects.symbol import Symbol


@dataclass
class Instrument:
    """A single tradeable instrument from the NSE instrument master.

    Lot sizes and tick sizes are stored as-is from the Kite download.
    Any lot size change detected on refresh must be confirmed by the operator
    before being applied (see docs/13_INSTRUMENT_MASTER.md §Lot Size Change).
    """

    instrument_id: uuid.UUID
    token: int
    symbol: Symbol
    name: str
    asset_type: AssetType
    exchange: str
    lot_size: int
    tick_size: Price
    is_active: bool = True
    expiry: date | None = None
    strike: Price | None = None
    instrument_type: str = ""
    segment: str = ""
    underlying_symbol: str | None = None
    option_type: str | None = None
    isin: str | None = None
    display_symbol: str = ""

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            msg = f"lot_size must be > 0, got {self.lot_size}"
            raise ValueError(msg)

    @classmethod
    def create(
        cls,
        token: int,
        symbol: Symbol,
        name: str,
        asset_type: AssetType,
        exchange: str,
        lot_size: int,
        tick_size: Decimal,
        expiry: date | None = None,
        strike: Decimal | None = None,
        instrument_type: str = "",
        segment: str = "",
        underlying_symbol: str | None = None,
        option_type: str | None = None,
        isin: str | None = None,
        display_symbol: str = "",
    ) -> Instrument:
        return cls(
            instrument_id=uuid.uuid4(),
            token=token,
            symbol=symbol,
            name=name,
            asset_type=asset_type,
            exchange=exchange,
            lot_size=lot_size,
            tick_size=Price(tick_size),
            expiry=expiry,
            strike=Price(strike) if strike is not None else None,
            instrument_type=instrument_type,
            segment=segment,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            isin=isin,
            display_symbol=display_symbol,
        )

    @property
    def is_fno(self) -> bool:
        return self.asset_type == AssetType.FNO

    @property
    def is_expired(self) -> bool:
        if self.expiry is None:
            return False
        return date.today() > self.expiry

    def deactivate(self) -> None:
        self.is_active = False
