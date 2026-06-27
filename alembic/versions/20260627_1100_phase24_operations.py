"""Phase 24 — Operations Mode.

Creates:
  incidents           — incident log (12 types, full history)
  scan_cycle_metrics  — per-scan-cycle performance metrics
  pre_market_checks   — daily pre-market checklist results

Revision ID: 20260627_1100
Revises: 20260627_1000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260627_1100"
down_revision = "20260627_1000"
branch_labels = None
depends_on    = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name=:t AND table_schema='public'"
        ),
        {"t": table},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    # ── incidents ─────────────────────────────────────────────────────────────
    if not _table_exists("incidents"):
        op.create_table(
            "incidents",
            sa.Column("id",               sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("incident_type",    sa.String(60),   nullable=False),
            sa.Column("severity",         sa.String(20),   nullable=False),
            sa.Column("title",            sa.Text(),       nullable=False),
            sa.Column("start_time",       sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("end_time",         sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_minutes", sa.Numeric(8, 1), nullable=True),
            sa.Column("root_cause",       sa.Text(),       nullable=True),
            sa.Column("resolution",       sa.Text(),       nullable=True),
            sa.Column("impact",           sa.Text(),       nullable=True),
            sa.Column("recovery_actions", sa.Text(),       nullable=True),
            sa.Column("is_resolved",      sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("created_at",       sa.DateTime(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at",       sa.DateTime(timezone=True),
                      nullable=False, server_default=sa.func.now()),
        )
        op.create_index("idx_incidents_type_start",      "incidents", ["incident_type", "start_time"])
        op.create_index("idx_incidents_severity_start",  "incidents", ["severity", "start_time"])
        op.create_index("idx_incidents_is_resolved",     "incidents", ["is_resolved", "start_time"])

    # ── scan_cycle_metrics ────────────────────────────────────────────────────
    if not _table_exists("scan_cycle_metrics"):
        op.create_table(
            "scan_cycle_metrics",
            sa.Column("id",                       sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("cycle_at",                 sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("scan_duration_seconds",    sa.Numeric(8, 3), nullable=True),
            sa.Column("symbols_scanned",          sa.Integer(),    nullable=True),
            sa.Column("symbols_failed",           sa.Integer(),    nullable=True),
            sa.Column("signals_generated",        sa.Integer(),    nullable=True),
            sa.Column("signals_rejected",         sa.Integer(),    nullable=True),
            sa.Column("signals_gated",            sa.Integer(),    nullable=True),
            sa.Column("avg_score",                sa.Numeric(6, 2), nullable=True),
            sa.Column("avg_confidence",           sa.Numeric(6, 2), nullable=True),
            sa.Column("avg_data_quality",         sa.Numeric(6, 2), nullable=True),
            sa.Column("india_vix",                sa.Numeric(6, 2), nullable=True),
            sa.Column("market_context",           sa.String(40),   nullable=True),
            sa.Column("execution_mode",           sa.String(20),   nullable=True),
            sa.Column("gate_failures",            sa.Text(),       nullable=True),
        )
        op.create_index("idx_scm_cycle_at", "scan_cycle_metrics", ["cycle_at"])

    # ── pre_market_checks ─────────────────────────────────────────────────────
    if not _table_exists("pre_market_checks"):
        op.create_table(
            "pre_market_checks",
            sa.Column("id",                   sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("check_date",           sa.Date(),       nullable=False),
            sa.Column("check_time",           sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("db_connected",         sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("redis_connected",      sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("kite_authenticated",   sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("websocket_connected",  sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("scanner_healthy",      sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("option_chain_healthy", sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("candles_available",    sa.Boolean(),    nullable=False, server_default="false"),
            sa.Column("execution_lock_mode",  sa.String(20),   nullable=True),
            sa.Column("overall_status",       sa.String(20),   nullable=False, server_default="'UNKNOWN'"),
            sa.Column("failed_checks",        sa.Text(),       nullable=True),
            sa.Column("notes",                sa.Text(),       nullable=True),
        )
        op.create_index("idx_pmc_check_date", "pre_market_checks", ["check_date"])


def downgrade() -> None:
    op.drop_table("pre_market_checks")
    op.drop_table("scan_cycle_metrics")
    op.drop_table("incidents")
