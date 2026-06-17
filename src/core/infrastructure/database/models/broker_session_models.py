"""ORM model for the broker_sessions table.

Stores encrypted broker access tokens. The plaintext token is never
written to the database.

Reference: docs/23_SECURITY_BASELINE.md §1.1 Broker Access Token Encryption
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.infrastructure.database.models.base import Base


class BrokerSessionOrm(Base):
    __tablename__ = "broker_sessions"

    id: Mapped[UUID] = mapped_column(
        "session_id", Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    broker_name: Mapped[str] = mapped_column(String(30), nullable=False)
    api_key: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_broker_sessions_broker_active", "broker_name", "is_active"),
    )
