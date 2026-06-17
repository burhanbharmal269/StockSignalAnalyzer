"""SqlAlchemyUserRepository — implements IUserRepository against PostgreSQL/SQLite.

ORM ↔ domain mapping:
  UserOrm.is_admin=True  →  UserRole.ADMIN
  UserOrm.is_admin=False →  UserRole.VIEWER
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.domain.entities.user import User
from core.domain.enums.user_role import UserRole
from core.domain.interfaces.i_user_repository import IUserRepository
from core.infrastructure.database.models.user_models import UserOrm


def _to_domain(orm: UserOrm) -> User:
    return User(
        user_id=str(orm.user_id),
        username=orm.username,
        hashed_password=orm.hashed_password,
        role=UserRole.ADMIN if orm.is_admin else UserRole.VIEWER,
        is_active=orm.is_active,
        force_change=orm.force_change,
        created_at=orm.created_at,
        last_login_at=orm.last_login_at,
    )


class SqlAlchemyUserRepository(IUserRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_by_username(self, username: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserOrm).where(UserOrm.username == username)
            )
            return _to_domain(row) if row is not None else None

    async def find_by_id(self, user_id: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserOrm).where(UserOrm.user_id == uuid.UUID(user_id))
            )
            return _to_domain(row) if row is not None else None

    async def create(self, user: User) -> None:
        async with self._session_factory() as session:
            orm = UserOrm(
                user_id=uuid.UUID(user.user_id),
                username=user.username,
                email=f"{user.username}@localhost",
                hashed_password=user.hashed_password,
                is_admin=(user.role == UserRole.ADMIN),
                is_active=user.is_active,
                force_change=user.force_change,
            )
            session.add(orm)
            await session.commit()

    async def update_password(
        self, user_id: str, hashed_password: str, force_change: bool
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(UserOrm)
                .where(UserOrm.user_id == uuid.UUID(user_id))
                .values(hashed_password=hashed_password, force_change=force_change)
            )
            await session.commit()

    async def update_last_login(self, user_id: str, timestamp: datetime) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(UserOrm)
                .where(UserOrm.user_id == uuid.UUID(user_id))
                .values(last_login_at=timestamp)
            )
            await session.commit()

    async def has_any_admin(self) -> bool:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserOrm).where(UserOrm.is_admin.is_(True)).limit(1)
            )
            return row is not None
