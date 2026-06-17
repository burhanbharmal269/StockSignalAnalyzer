"""SQLAlchemy ORM model for the regime_snapshots table.

This is a regular relational table (not a hypertable).
Indexed on (instrument_token, timeframe, evaluated_at) for fast latest-lookup.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class RegimeSnapshotOrm(Base):
    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_token: Mapped[int] = mapped_column(Integer, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    primary_regime: Mapped[str] = mapped_column(String(30), nullable=False)
    secondary_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    direction_layer: Mapped[str] = mapped_column(String(10), nullable=False)
    volatility_layer: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False)
    regime_duration_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_signal: Mapped[bool] = mapped_column(Integer, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_regime_snapshots_token_tf_time",
            "instrument_token",
            "timeframe",
            "evaluated_at",
        ),
    )
