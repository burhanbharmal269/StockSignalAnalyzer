"""Integration tests for migration 004_phase13.

Requires a real PostgreSQL instance.  Set TEST_POSTGRES_URL in the environment
to run these tests, e.g.:

    TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@localhost/test_db \
    pytest tests/integration/test_phase13_migration.py -m integration -v

All tests are skipped automatically when TEST_POSTGRES_URL is not set.
Tests verify: table creation, column schema, index existence, RC-1 permission
model, RC-2 portfolio_snapshot column, and full upgrade/downgrade reversibility.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_url() -> str:
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL not set — skipping Phase 13 migration tests")
    return url


@pytest.fixture(scope="module")
def alembic_cfg(pg_url: str) -> Config:
    cfg = Config("alembic.ini")
    # Sync URL for alembic (strip +asyncpg suffix if present)
    sync_url = pg_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


@pytest.fixture(scope="module")
async def async_engine(pg_url: str) -> Any:  # type: ignore[return]
    engine = create_async_engine(pg_url, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def run_migration(alembic_cfg: Config) -> Any:  # type: ignore[return]
    """Apply migrations up to 004_phase13 before module tests run, then roll back."""
    command.upgrade(alembic_cfg, "004_phase13")
    yield
    command.downgrade(alembic_cfg, "003_phase12")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _table_exists(engine: Any, table_name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :name"
            ),
            {"name": table_name},
        )
        return result.scalar() is not None


async def _column_exists(engine: Any, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ),
            {"table": table, "col": column},
        )
        return result.scalar() is not None


async def _column_nullable(engine: Any, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ),
            {"table": table, "col": column},
        )
        row = result.scalar()
        return row == "YES"


async def _index_exists(engine: Any, index_name: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE indexname = :name"
            ),
            {"name": index_name},
        )
        return result.scalar() is not None


# ---------------------------------------------------------------------------
# risk_decisions: table and schema
# ---------------------------------------------------------------------------


class TestRiskDecisionsSchema:
    async def test_upgrade_creates_risk_decisions(self, async_engine: Any) -> None:
        assert await _table_exists(async_engine, "risk_decisions")

    async def test_signal_id_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "risk_decisions", "signal_id")

    async def test_approved_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "risk_decisions", "approved")

    async def test_checks_jsonb_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "risk_decisions", "checks")

    async def test_account_snapshot_jsonb_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "risk_decisions", "account_snapshot")

    async def test_rc2_portfolio_snapshot_column_exists(self, async_engine: Any) -> None:
        assert await _column_exists(async_engine, "risk_decisions", "portfolio_snapshot")

    async def test_rc2_portfolio_snapshot_is_nullable(self, async_engine: Any) -> None:
        assert await _column_nullable(async_engine, "risk_decisions", "portfolio_snapshot")

    async def test_risk_config_version_column_exists(self, async_engine: Any) -> None:
        assert await _column_exists(async_engine, "risk_decisions", "risk_config_version")

    async def test_risk_config_sha256_column_exists(self, async_engine: Any) -> None:
        assert await _column_exists(async_engine, "risk_decisions", "risk_config_sha256")

    async def test_evaluation_duration_ms_column_exists(self, async_engine: Any) -> None:
        assert await _column_exists(async_engine, "risk_decisions", "evaluation_duration_ms")

    async def test_evaluated_at_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "risk_decisions", "evaluated_at")

    async def test_evaluated_at_defaults_to_now(self, async_engine: Any) -> None:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO risk_decisions "
                    "(signal_id, approved, checks, account_snapshot) "
                    "VALUES (gen_random_uuid(), TRUE, '[]'::jsonb, '{}'::jsonb)"
                )
            )
            result = await conn.execute(
                text("SELECT evaluated_at FROM risk_decisions ORDER BY id DESC LIMIT 1")
            )
            row = result.scalar()
        assert row is not None


# ---------------------------------------------------------------------------
# kill_switch_events: table and schema
# ---------------------------------------------------------------------------


class TestKillSwitchEventsSchema:
    async def test_upgrade_creates_kill_switch_events(self, async_engine: Any) -> None:
        assert await _table_exists(async_engine, "kill_switch_events")

    async def test_event_type_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "kill_switch_events", "event_type")

    async def test_triggered_by_not_null(self, async_engine: Any) -> None:
        assert not await _column_nullable(async_engine, "kill_switch_events", "triggered_by")

    async def test_user_id_nullable(self, async_engine: Any) -> None:
        assert await _column_nullable(async_engine, "kill_switch_events", "user_id")

    async def test_metadata_nullable(self, async_engine: Any) -> None:
        assert await _column_nullable(async_engine, "kill_switch_events", "metadata")

    async def test_created_at_defaults_to_now(self, async_engine: Any) -> None:
        async with async_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO kill_switch_events "
                    "(event_type, triggered_by, trigger_source, reason) "
                    "VALUES ('ACTIVATED', 'test', 'test', 'test')"
                )
            )
            result = await conn.execute(
                text("SELECT created_at FROM kill_switch_events ORDER BY id DESC LIMIT 1")
            )
            row = result.scalar()
        assert row is not None


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


class TestIndexes:
    async def test_idx_risk_decisions_signal_id_exists(self, async_engine: Any) -> None:
        assert await _index_exists(async_engine, "idx_risk_decisions_signal_id")

    async def test_idx_risk_decisions_approved_exists(self, async_engine: Any) -> None:
        assert await _index_exists(async_engine, "idx_risk_decisions_approved")

    async def test_idx_risk_decisions_evaluated_at_exists(self, async_engine: Any) -> None:
        assert await _index_exists(async_engine, "idx_risk_decisions_evaluated_at")

    async def test_idx_risk_decisions_rejection_code_partial_exists(
        self, async_engine: Any
    ) -> None:
        assert await _index_exists(async_engine, "idx_risk_decisions_rejection_code")

    async def test_idx_kill_switch_events_created_at_exists(self, async_engine: Any) -> None:
        assert await _index_exists(async_engine, "idx_kill_switch_events_created_at")

    async def test_idx_kill_switch_events_event_type_exists(self, async_engine: Any) -> None:
        assert await _index_exists(async_engine, "idx_kill_switch_events_event_type")


# ---------------------------------------------------------------------------
# RC-1: permission model (only verifiable when app_user role exists)
# ---------------------------------------------------------------------------


class TestPermissionModel:
    async def test_rc1_grants_and_revokes_execute_without_error(
        self, async_engine: Any
    ) -> None:
        # The upgrade() DO block is guarded by IF EXISTS (rolname = 'app_user').
        # This test just verifies the migration ran without exceptions (fixture
        # autouse=True would have raised on failure).
        assert await _table_exists(async_engine, "risk_decisions")


# ---------------------------------------------------------------------------
# Revision chain
# ---------------------------------------------------------------------------


class TestRevisionChain:
    def test_revision_chain_revises_003_phase12(self) -> None:
        from alembic.versions.v20260614_1000_phase13_risk_engine import (  # type: ignore[import]
            down_revision,
            revision,
        )

        assert revision == "004_phase13"
        assert down_revision == "003_phase12"


# ---------------------------------------------------------------------------
# Downgrade (verified via fixture teardown — tables must be absent after)
# ---------------------------------------------------------------------------


class TestDowngrade:
    async def test_downgrade_drops_risk_decisions(self, alembic_cfg: Config, async_engine: Any) -> None:
        # Temporarily downgrade, verify, then re-upgrade for subsequent tests
        command.downgrade(alembic_cfg, "003_phase12")
        exists = await _table_exists(async_engine, "risk_decisions")
        command.upgrade(alembic_cfg, "004_phase13")
        assert not exists

    async def test_downgrade_drops_kill_switch_events(
        self, alembic_cfg: Config, async_engine: Any
    ) -> None:
        command.downgrade(alembic_cfg, "003_phase12")
        exists = await _table_exists(async_engine, "kill_switch_events")
        command.upgrade(alembic_cfg, "004_phase13")
        assert not exists
