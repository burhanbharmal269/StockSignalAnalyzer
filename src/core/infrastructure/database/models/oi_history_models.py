"""ORM model for oi_history_snapshots table — Phase 21.1 Part 2.

Stores lightweight periodic OI snapshots for historical analytics,
feature evaluation, and AI/ML dataset preparation.

Populated every snapshot_interval_seconds by OIAnalyticsService.
Never read during live trading — purely for post-trade intelligence.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class OIHistorySnapshotOrm(Base):
    __tablename__ = "oi_history_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Symbol identity
    symbol:        Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tradingsymbol: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. NIFTY26JULFUT
    expiry:        Mapped[date] = mapped_column(Date, nullable=False)

    # Price + OI raw values
    futures_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    oi:            Mapped[int | None]   = mapped_column(BigInteger, nullable=True)
    previous_oi:   Mapped[int | None]   = mapped_column(BigInteger, nullable=True)
    oi_change:     Mapped[int | None]   = mapped_column(BigInteger, nullable=True)
    oi_change_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Classified fields
    oi_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Increasing/Falling/Flat
    oi_regime:    Mapped[str | None] = mapped_column(String(30), nullable=True)  # Long Build-up / etc.

    # Rolling averages (from FuturesOIService rolling buffers)
    rolling_avg_5:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rolling_avg_15: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rolling_avg_60: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Price context
    price_change_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Quality
    quality_tier:  Mapped[str | None] = mapped_column(String(20), nullable=True)  # Excellent/Good/Fair/Poor
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)     # 0-100

    # Freshness
    cache_age_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Anomaly flags
    is_anomaly:    Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False)
    anomaly_type:  Mapped[str | None]  = mapped_column(String(50), nullable=True)  # SPIKE/FREEZE/COLLAPSE/STALE

    # Contract roll flag
    is_contract_roll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_oi_hist_symbol_at",  "symbol", "snapshot_at"),
        Index("idx_oi_hist_regime",     "oi_regime", "snapshot_at"),
        Index("idx_oi_hist_anomaly",    "is_anomaly", "snapshot_at"),
    )
