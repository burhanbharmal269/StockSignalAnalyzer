"""Phase 25 — Platform Freeze, Experiment Framework & Evidence-Driven Evolution.

Creates:
  experiments            — A/B experiment registry
  experiment_signals     — per-signal group assignment (CONTROL|TREATMENT)
  platform_events        — audit log: freeze, unfreeze, approval, governance events

Adds to signal_analytics:
  strategy_version       — pinned version string at signal creation time
  risk_version           — risk engine version
  target_version         — target/stop engine version
  experiment_id          — FK to experiments.experiment_id (nullable)
  ab_group               — CONTROL | TREATMENT | NONE

Revision ID: 20260630_1000
Revises: 20260630_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260630_1000"
down_revision = "20260630_0900"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── experiments ────────────────────────────────────────────────────────────
    op.create_table(
        "experiments",
        sa.Column("id",                          sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("experiment_id",               sa.String(20),   nullable=False, unique=True),
        sa.Column("title",                       sa.String(200),  nullable=False),
        sa.Column("description",                 sa.Text(),       nullable=True),
        sa.Column("hypothesis",                  sa.Text(),       nullable=False),
        sa.Column("author",                      sa.String(100),  nullable=False),
        sa.Column("status",                      sa.String(20),   nullable=False, server_default="DRAFT"),
        sa.Column("baseline_strategy_version",   sa.String(50),   nullable=True),
        sa.Column("candidate_strategy_version",  sa.String(50),   nullable=True),
        sa.Column("minimum_sample_size",         sa.Integer(),    nullable=False, server_default="50"),
        sa.Column("preferred_sample_size",       sa.Integer(),    nullable=False, server_default="200"),
        sa.Column("primary_kpi",                 sa.String(60),   nullable=False, server_default="win_rate"),
        sa.Column("secondary_kpi",               sa.String(60),   nullable=True),
        sa.Column("expected_improvement_pct",    sa.Numeric(6, 2), nullable=True),
        sa.Column("failure_criteria",            sa.Text(),       nullable=True),
        sa.Column("success_threshold",           sa.Numeric(6, 2), nullable=True),
        sa.Column("max_drawdown_allowed",        sa.Numeric(6, 2), nullable=True),
        sa.Column("rollback_plan",               sa.Text(),       nullable=True),
        sa.Column("treatment_allocation_pct",    sa.Numeric(5, 2), nullable=False, server_default="10.0"),
        sa.Column("approval_status",             sa.String(20),   nullable=False, server_default="PENDING"),
        sa.Column("approved_by",                 sa.String(100),  nullable=True),
        sa.Column("approved_at",                 sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes",                       sa.Text(),       nullable=True),
        sa.Column("conclusion",                  sa.Text(),       nullable=True),
        sa.Column("created_at",                  sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("started_at",                  sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at",                sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_exp_status",       "experiments", ["status"])
    op.create_index("idx_exp_approval",     "experiments", ["approval_status"])

    # ── experiment_signals ─────────────────────────────────────────────────────
    op.create_table(
        "experiment_signals",
        sa.Column("id",             sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("experiment_id",  sa.String(20),   nullable=False),
        sa.Column("signal_id",      sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_type",     sa.String(10),   nullable=False),   # CONTROL | TREATMENT
        sa.Column("assigned_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("analytics_id",   sa.BigInteger(), nullable=True),    # FK to signal_analytics.id
    )
    op.create_index("idx_expsig_experiment", "experiment_signals", ["experiment_id"])
    op.create_index("idx_expsig_signal",     "experiment_signals", ["signal_id"])

    # ── platform_events ────────────────────────────────────────────────────────
    op.create_table(
        "platform_events",
        sa.Column("id",          sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type",  sa.String(40),   nullable=False),  # FREEZE|UNFREEZE|APPROVE|REJECT|GOVERNANCE_PASS|GOVERNANCE_FAIL
        sa.Column("actor",       sa.String(100),  nullable=True),
        sa.Column("description", sa.Text(),       nullable=True),
        sa.Column("payload_json", sa.Text(),      nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_pevt_type",       "platform_events", ["event_type"])
    op.create_index("idx_pevt_created_at", "platform_events", ["created_at"])

    # ── signal_analytics additions ─────────────────────────────────────────────
    op.add_column("signal_analytics", sa.Column("strategy_version", sa.String(50), nullable=True))
    op.add_column("signal_analytics", sa.Column("risk_version",     sa.String(50), nullable=True))
    op.add_column("signal_analytics", sa.Column("target_version",   sa.String(50), nullable=True))
    op.add_column("signal_analytics", sa.Column("experiment_id",    sa.String(20), nullable=True))
    op.add_column("signal_analytics", sa.Column("ab_group",         sa.String(10), nullable=True))

    op.create_index("idx_sa_experiment_id", "signal_analytics", ["experiment_id"],
                    postgresql_where=sa.text("experiment_id IS NOT NULL"))
    op.create_index("idx_sa_strategy_version", "signal_analytics", ["strategy_version"],
                    postgresql_where=sa.text("strategy_version IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("idx_sa_strategy_version", table_name="signal_analytics")
    op.drop_index("idx_sa_experiment_id",    table_name="signal_analytics")
    op.drop_column("signal_analytics", "ab_group")
    op.drop_column("signal_analytics", "experiment_id")
    op.drop_column("signal_analytics", "target_version")
    op.drop_column("signal_analytics", "risk_version")
    op.drop_column("signal_analytics", "strategy_version")

    op.drop_index("idx_pevt_created_at", table_name="platform_events")
    op.drop_index("idx_pevt_type",       table_name="platform_events")
    op.drop_table("platform_events")

    op.drop_index("idx_expsig_signal",     table_name="experiment_signals")
    op.drop_index("idx_expsig_experiment", table_name="experiment_signals")
    op.drop_table("experiment_signals")

    op.drop_index("idx_exp_approval", table_name="experiments")
    op.drop_index("idx_exp_status",   table_name="experiments")
    op.drop_table("experiments")
