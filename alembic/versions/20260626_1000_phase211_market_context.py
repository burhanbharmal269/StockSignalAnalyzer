"""Phase 21.1 — Market Context Engine, Event Calendar, overlay attribution columns.

Creates:
  market_context_snapshots  — one row per scan cycle; records NORMAL/CAUTION/HIGH_RISK/PANIC
  event_calendar            — event store; auto-seeded for NSE expiry, manual for macro events
  regime_transition_log     — per-symbol regime change history for stability overlay

Adds to signal_analytics:
  market_context, market_context_adj, event_adj,
  regime_stability, regime_stability_adj,
  confidence_attribution_json, event_overlay_json,
  context_size_multiplier, overlay_adjusted_confidence,
  execution_grade

Revision ID: 20260626_1000
Revises: 20260620_1000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260626_1000"
down_revision = "20260620_1000"
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


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c AND table_schema='public'"
        ),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def _index_exists(idx: str) -> bool:
    bind = op.get_bind()
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname=:i AND schemaname='public'"
        ),
        {"i": idx},
    )
    return r.fetchone() is not None


def upgrade() -> None:
    # ── market_context_snapshots ──────────────────────────────────────────────
    if not _table_exists("market_context_snapshots"):
        op.create_table(
            "market_context_snapshots",
            sa.Column("id",           sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("level",        sa.String(20),   nullable=False),
            sa.Column("confidence_adj", sa.Numeric(5, 2), nullable=True),
            sa.Column("size_multiplier", sa.Numeric(4, 3), nullable=True),
            sa.Column("reason",       sa.Text(),       nullable=True),
            sa.Column("context_score", sa.Integer(),   nullable=True),
            sa.Column("nifty_regime", sa.String(30),   nullable=True),
            sa.Column("bnf_regime",   sa.String(30),   nullable=True),
            sa.Column("finnifty_regime", sa.String(30), nullable=True),
            sa.Column("vix",          sa.Numeric(6, 2), nullable=True),
            sa.Column("vix_rising",   sa.Boolean(),    nullable=True),
            sa.Column("breadth_score", sa.Numeric(5, 2), nullable=True),
            sa.Column("advance_decline_ratio", sa.Numeric(6, 3), nullable=True),
            sa.Column("computed_at",  sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_mcs_computed_at", "market_context_snapshots", ["computed_at"])
        op.create_index("idx_mcs_level",       "market_context_snapshots", ["level", "computed_at"])

    # ── event_calendar ────────────────────────────────────────────────────────
    if not _table_exists("event_calendar"):
        op.create_table(
            "event_calendar",
            sa.Column("id",               sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("event_type",       sa.String(40),   nullable=False),
            sa.Column("event_name",       sa.String(120),  nullable=False),
            sa.Column("severity",         sa.String(20),   nullable=False),
            sa.Column("affected_symbols", sa.JSON(),       nullable=True),   # NULL = all symbols
            sa.Column("start_time",       sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_time",         sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason",           sa.Text(),       nullable=True),
            sa.Column("source",           sa.String(20),   server_default="MANUAL", nullable=False),
            sa.Column("is_active",        sa.Boolean(),    server_default="true",   nullable=False),
            sa.Column("created_at",       sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_ec_active_time",   "event_calendar",
                        ["is_active", "start_time", "end_time"])
        op.create_index("idx_ec_event_type",    "event_calendar", ["event_type", "start_time"])

        # Dedup index for auto-seeded events: one event per (type, day, source)
        if not _index_exists("idx_ec_auto_dedup"):
            op.get_bind().execute(sa.text("""
                CREATE UNIQUE INDEX idx_ec_auto_dedup
                ON event_calendar (event_type, (start_time::date), source)
                WHERE source = 'AUTO'
            """))

    # ── regime_transition_log ─────────────────────────────────────────────────
    if not _table_exists("regime_transition_log"):
        op.create_table(
            "regime_transition_log",
            sa.Column("id",              sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("symbol",          sa.String(20),   nullable=False),
            sa.Column("from_regime",     sa.String(30),   nullable=True),
            sa.Column("to_regime",       sa.String(30),   nullable=False),
            sa.Column("stability_label", sa.String(20),   nullable=True),
            sa.Column("stability_adj",   sa.Numeric(5, 2), nullable=True),
            sa.Column("logged_at",       sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_rtl_symbol", "regime_transition_log", ["symbol", "logged_at"])

    # ── signal_analytics — new overlay columns ────────────────────────────────
    new_cols = [
        ("market_context",              sa.String(20)),
        ("market_context_adj",          sa.Numeric(5, 2)),
        ("event_adj",                   sa.Numeric(5, 2)),
        ("event_overlay_json",          sa.Text()),
        ("regime_stability",            sa.String(20)),
        ("regime_stability_adj",        sa.Numeric(5, 2)),
        ("confidence_attribution_json", sa.Text()),
        ("context_size_multiplier",     sa.Numeric(4, 3)),
        ("overlay_adjusted_confidence", sa.Numeric(5, 2)),
        ("execution_grade",             sa.String(5)),
    ]
    for col_name, col_type in new_cols:
        if not _col_exists("signal_analytics", col_name):
            op.add_column("signal_analytics", sa.Column(col_name, col_type, nullable=True))

    if not _index_exists("idx_sa_market_context"):
        op.create_index("idx_sa_market_context", "signal_analytics",
                        ["market_context", "created_at"])


def downgrade() -> None:
    # Drop overlay columns from signal_analytics
    overlay_cols = [
        "market_context", "market_context_adj", "event_adj", "event_overlay_json",
        "regime_stability", "regime_stability_adj", "confidence_attribution_json",
        "context_size_multiplier", "overlay_adjusted_confidence", "execution_grade",
    ]
    for col in overlay_cols:
        if _col_exists("signal_analytics", col):
            op.drop_column("signal_analytics", col)

    if _index_exists("idx_sa_market_context"):
        op.drop_index("idx_sa_market_context", table_name="signal_analytics")

    for table, indexes in [
        ("regime_transition_log", ["idx_rtl_symbol"]),
        ("event_calendar",        ["idx_ec_active_time", "idx_ec_event_type", "idx_ec_auto_dedup"]),
        ("market_context_snapshots", ["idx_mcs_computed_at", "idx_mcs_level"]),
    ]:
        if _table_exists(table):
            for idx in indexes:
                if _index_exists(idx):
                    op.drop_index(idx, table_name=table)
            op.drop_table(table)
