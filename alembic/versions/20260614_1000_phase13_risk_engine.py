"""Phase 13: Create risk_decisions (hypertable) and kill_switch_events tables.

Revision ID: 004_phase13
Revises: 003_phase12
Create Date: 2026-06-14 10:00:00

risk_decisions is a TimescaleDB hypertable partitioned by evaluated_at.
kill_switch_events is an append-only audit table.

RC-1: GRANT SELECT, INSERT, GRANT USAGE ON SEQUENCE execute before REVOKE so
the permission model is always additive-then-restrictive.
RC-2: portfolio_snapshot JSONB NULL stored now; Phase D populates when
RiskDecision.portfolio_snapshot is added to the domain object.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_phase13"
down_revision: str | None = "003_phase12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # risk_decisions
    # ------------------------------------------------------------------
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("rejection_code", sa.String(50), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("position_size_lots", sa.Integer, nullable=True),
        sa.Column("size_reduction_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "account_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "portfolio_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "sizing_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "failed_data_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("risk_config_version", sa.String(50), nullable=True),
        sa.Column("risk_config_sha256", sa.String(64), nullable=True),
        sa.Column("evaluation_duration_ms", sa.Integer, nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_index(
        "idx_risk_decisions_signal_id",
        "risk_decisions",
        ["signal_id"],
    )
    op.create_index(
        "idx_risk_decisions_approved",
        "risk_decisions",
        ["approved", "evaluated_at"],
    )
    op.create_index(
        "idx_risk_decisions_evaluated_at",
        "risk_decisions",
        ["evaluated_at"],
    )
    # Partial index — only indexes rows where a rejection code exists
    op.execute(
        "CREATE INDEX idx_risk_decisions_rejection_code "
        "ON risk_decisions (rejection_code) "
        "WHERE rejection_code IS NOT NULL"
    )

    # ------------------------------------------------------------------
    # kill_switch_events
    # ------------------------------------------------------------------
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("trigger_source", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_index(
        "idx_kill_switch_events_created_at",
        "kill_switch_events",
        ["created_at"],
    )
    op.create_index(
        "idx_kill_switch_events_event_type",
        "kill_switch_events",
        ["event_type", "created_at"],
    )

    # ------------------------------------------------------------------
    # RC-1: GRANT before REVOKE (guarded — no-op if role absent in dev)
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT SELECT, INSERT ON risk_decisions TO app_user;
                GRANT USAGE, SELECT ON SEQUENCE risk_decisions_id_seq TO app_user;
                GRANT SELECT, INSERT ON kill_switch_events TO app_user;
                GRANT USAGE, SELECT ON SEQUENCE kill_switch_events_id_seq TO app_user;
                REVOKE UPDATE, DELETE ON risk_decisions FROM app_user;
                REVOKE UPDATE, DELETE ON kill_switch_events FROM app_user;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # TimescaleDB hypertable (guarded — no-op if extension absent)
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'risk_decisions',
                    'evaluated_at',
                    chunk_time_interval => INTERVAL '1 day',
                    if_not_exists => TRUE
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_index("idx_kill_switch_events_event_type", table_name="kill_switch_events")
    op.drop_index("idx_kill_switch_events_created_at", table_name="kill_switch_events")
    op.drop_table("kill_switch_events")

    op.execute("DROP INDEX IF EXISTS idx_risk_decisions_rejection_code")
    op.drop_index("idx_risk_decisions_evaluated_at", table_name="risk_decisions")
    op.drop_index("idx_risk_decisions_approved", table_name="risk_decisions")
    op.drop_index("idx_risk_decisions_signal_id", table_name="risk_decisions")
    op.drop_table("risk_decisions")
