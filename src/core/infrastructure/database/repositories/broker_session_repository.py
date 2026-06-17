"""SQLAlchemy implementation of IBrokerSessionRepository.

Reference: docs/23_SECURITY_BASELINE.md §1.1 Broker Access Token Encryption
"""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.broker_session import BrokerSession
from core.domain.interfaces.i_broker_session_repository import IBrokerSessionRepository
from core.infrastructure.database.models.broker_session_models import BrokerSessionOrm


def _to_domain(row: BrokerSessionOrm) -> BrokerSession:
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return BrokerSession(
        session_id=row.id,
        broker_name=row.broker_name,
        api_key=row.api_key,
        encrypted_access_token=row.encrypted_access_token,
        expires_at=expires_at,
        is_active=row.is_active,
        created_at=(
            row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at
        ),
        user_name=row.user_name or "",
    )


class SqlAlchemyBrokerSessionRepository(IBrokerSessionRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, session: BrokerSession) -> None:
        async with self._session_factory() as db:
            existing = await db.get(BrokerSessionOrm, session.session_id)
            if existing is None:
                db.add(
                    BrokerSessionOrm(
                        id=session.session_id,
                        broker_name=session.broker_name,
                        api_key=session.api_key,
                        encrypted_access_token=session.encrypted_access_token,
                        expires_at=session.expires_at,
                        is_active=session.is_active,
                        user_name=session.user_name,
                    )
                )
            else:
                existing.encrypted_access_token = session.encrypted_access_token
                existing.expires_at = session.expires_at
                existing.is_active = session.is_active
                existing.user_name = session.user_name
            await db.commit()

    async def get_active(self, broker_name: str) -> BrokerSession | None:
        async with self._session_factory() as db:
            result = await db.execute(
                select(BrokerSessionOrm).where(
                    BrokerSessionOrm.broker_name == broker_name,
                    BrokerSessionOrm.is_active.is_(True),
                )
            )
            row = result.scalar_one_or_none()
            return _to_domain(row) if row else None

    async def get_by_id(self, session_id: uuid.UUID) -> BrokerSession | None:
        async with self._session_factory() as db:
            row = await db.get(BrokerSessionOrm, session_id)
            return _to_domain(row) if row else None

    async def deactivate_all(self, broker_name: str) -> None:
        async with self._session_factory() as db:
            await db.execute(
                update(BrokerSessionOrm)
                .where(BrokerSessionOrm.broker_name == broker_name)
                .values(is_active=False)
            )
            await db.commit()
