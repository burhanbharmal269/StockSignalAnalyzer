"""ORM models for TimescaleDB hypertables: market_data, option_chain, market_features.

These are regular SQLAlchemy models — Alembic migration converts them to hypertables.
Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class MarketDataOrm(Base):
    """Hypertable: market_data. Partition key: timestamp."""

    __tablename__ = "market_data"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    instrument_token: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    buy_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    data_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)


class OptionChainOrm(Base):
    """Hypertable: option_chain. Partition key: timestamp."""

    __tablename__ = "option_chain"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    instrument_token: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    underlying_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    expiry_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    strike_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(2), nullable=False)
    last_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    bid_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ask_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    oi_change: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iv: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    theta: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    vega: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)


class MarketFeaturesOrm(Base):
    """Hypertable: market_features. Partition key: timestamp."""

    __tablename__ = "market_features"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    instrument_token: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False)
    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    ema_9: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ema_21: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ema_50: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ema_200: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    sma_20: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    atr_14: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    macd_line: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    macd_signal: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    macd_histogram: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    adx_14: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    supertrend: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    supertrend_dir: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_upper: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bb_lower: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bb_width: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    relative_volume: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    volume_sma_20: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pcr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    max_pain: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    iv_rank: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    iv_percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
