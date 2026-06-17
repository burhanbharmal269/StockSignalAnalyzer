"""Shared fixtures for database repository unit tests.

Uses SQLite in-memory via aiosqlite. Only the tables exercised by unit tests
(signals, orders, positions, instruments) are created. Hypertables
(market_data, option_chain, market_features, signal_events, order_events)
require real TimescaleDB and are covered by integration tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.infrastructure.database.models.base import Base
from core.infrastructure.database.models.broker_session_models import BrokerSessionOrm  # noqa: F401
from core.infrastructure.database.models.instrument_models import InstrumentOrm  # noqa: F401
from core.infrastructure.database.models.order_models import OrderOrm  # noqa: F401
from core.infrastructure.database.models.position_models import PositionOrm  # noqa: F401
from core.infrastructure.database.models.regime_models import RegimeSnapshotOrm  # noqa: F401
from core.infrastructure.database.models.risk_models import KillSwitchEventModel  # noqa: F401
from core.infrastructure.database.models.risk_models import RiskDecisionModel  # noqa: F401
from core.infrastructure.database.models.signal_models import SignalOrm  # noqa: F401

# Only create the tables the unit tests need (no hypertable or ARRAY-typed tables).
_UNIT_TEST_TABLES = {
    "broker_sessions",
    "signals",
    "orders",
    "positions",
    "instruments",
    "regime_snapshots",
}


def _create_unit_test_tables(conn: object) -> None:
    for table in Base.metadata.sorted_tables:
        if table.name in _UNIT_TEST_TABLES:
            table.create(conn, checkfirst=True)  # type: ignore[arg-type]


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_create_unit_test_tables)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return factory
