"""Async SQLAlchemy engine factory.

Two engines per doc 18: write engine (primary) and read engine (replica).
All connections go through PgBouncer in transaction-mode pooling.

Pool sizes per service type are configured via DatabaseConfig.
Never call create_async_engine directly outside this module.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_write_engine(
    url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_timeout: int = 30,
) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        echo=False,
    )


def build_read_engine(
    url: str,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 60,
) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
        echo=False,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
