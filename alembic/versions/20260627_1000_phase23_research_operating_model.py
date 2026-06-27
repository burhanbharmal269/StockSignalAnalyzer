"""Phase 23 — Research Operating Model.

Adds to signal_analytics:
  qualification_grade, qualification_reason, qualification_version,
  qualification_timestamp, deployment_stage

Creates:
  research_recommendations  — evidence-driven recommendations store
  weekly_research_snapshots — persisted weekly report blobs

Revision ID: 20260627_1000
Revises: 20260626_1100
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260627_1000"
down_revision = "20260626_1100"
branch_labels = None
depends_on    = None


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
    # ── signal_analytics — qualification + deployment stage ───────────────────
    with op.batch_alter_table("signal_analytics") as batch:
        if not _col_exists("signal_analytics", "qualification_grade"):
            batch.add_column(sa.Column("qualification_grade",     sa.String(5),   nullable=True))
        if not _col_exists("signal_analytics", "qualification_reason"):
            batch.add_column(sa.Column("qualification_reason",    sa.Text(),      nullable=True))
        if not _col_exists("signal_analytics", "qualification_version"):
            batch.add_column(sa.Column("qualification_version",   sa.String(20),  nullable=True))
        if not _col_exists("signal_analytics", "qualification_timestamp"):
            batch.add_column(sa.Column("qualification_timestamp", sa.DateTime(timezone=True), nullable=True))
        if not _col_exists("signal_analytics", "deployment_stage"):
            batch.add_column(sa.Column("deployment_stage",        sa.String(20),  nullable=True))

    op.get_bind().execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_sa_qual_grade
        ON signal_analytics (qualification_grade, created_at)
        WHERE qualification_grade IS NOT NULL
    """))
    op.get_bind().execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_sa_deployment_stage
        ON signal_analytics (deployment_stage, created_at)
        WHERE deployment_stage IS NOT NULL
    """))

    # ── research_recommendations ──────────────────────────────────────────────
    if not _table_exists("research_recommendations"):
        op.create_table(
            "research_recommendations",
            sa.Column("id",                     sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("recommendation_type",    sa.String(60),   nullable=False),
            sa.Column("dimension",              sa.String(60),   nullable=False),
            sa.Column("cohort_key",             sa.String(120),  nullable=True),
            sa.Column("direction",              sa.String(20),   nullable=False),
            sa.Column("trade_count",            sa.Integer(),    nullable=False, server_default="0"),
            sa.Column("z_statistic",            sa.Numeric(7, 3), nullable=True),
            sa.Column("p_value",                sa.Numeric(8, 6), nullable=True),
            sa.Column("ci_low",                 sa.Numeric(8, 4), nullable=True),
            sa.Column("ci_high",                sa.Numeric(8, 4), nullable=True),
            sa.Column("cohort_win_rate",        sa.Numeric(6, 3), nullable=True),
            sa.Column("baseline_win_rate",      sa.Numeric(6, 3), nullable=True),
            sa.Column("cohort_pf",              sa.Numeric(7, 3), nullable=True),
            sa.Column("expected_improvement",   sa.Text(),       nullable=True),
            sa.Column("risk_description",       sa.Text(),       nullable=True),
            sa.Column("rollback_plan",          sa.Text(),       nullable=True),
            sa.Column("status",                 sa.String(30),   nullable=False, server_default="'WAIT'"),
            sa.Column("created_at",             sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at",             sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_rr_status_created",  "research_recommendations", ["status", "created_at"])
        op.create_index("idx_rr_dimension",        "research_recommendations", ["dimension"])

    # ── weekly_research_snapshots ─────────────────────────────────────────────
    if not _table_exists("weekly_research_snapshots"):
        op.create_table(
            "weekly_research_snapshots",
            sa.Column("id",          sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("week_start",  sa.Date(),       nullable=False),
            sa.Column("week_end",    sa.Date(),       nullable=False),
            sa.Column("report_json", sa.Text(),       nullable=False),
            sa.Column("created_at",  sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_wrs_week_start", "weekly_research_snapshots", ["week_start"])


def downgrade() -> None:
    op.drop_table("weekly_research_snapshots")
    op.drop_table("research_recommendations")
    with op.batch_alter_table("signal_analytics") as batch:
        for col in ("deployment_stage", "qualification_timestamp",
                    "qualification_version", "qualification_reason", "qualification_grade"):
            batch.drop_column(col)
