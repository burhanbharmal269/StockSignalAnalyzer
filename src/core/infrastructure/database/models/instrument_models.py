"""ORM model for the instruments table.

Reference: docs/13_INSTRUMENT_MASTER.md
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class InstrumentOrm(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    token: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    instrument_type: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    segment: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    underlying_symbol: Mapped[str | None] = mapped_column(String(30), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    display_symbol: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InstrumentRefreshLogOrm(Base):
    """Persists the outcome of each instrument master refresh cycle.

    Reference: docs/13_INSTRUMENT_MASTER.md §instrument_refresh_log
    """

    __tablename__ = "instrument_refresh_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    instruments_added: Mapped[int] = mapped_column(Integer, nullable=False)
    instruments_updated: Mapped[int] = mapped_column(Integer, nullable=False)
    instruments_deactivated: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExpiryCalendarOrm(Base):
    """Stores pre-computed expiry dates with holiday adjustment metadata.

    Reference: docs/13_INSTRUMENT_MASTER.md §expiry_calendar
    """

    __tablename__ = "expiry_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    underlying_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    series: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_holiday_adjusted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    original_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
