"""Phase 19 — Reconciliation Engine: persisted runs and discrepancies.

Revision ID: 008_phase19
Revises: 007_phase18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "008_phase19"
down_revision = "007_phase18"
branch_labels = None
depends_on = None

_JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "reconciliation_runs",
        sa.Column("run_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("broker_name", sa.String(30), nullable=False),
        sa.Column("trigger", sa.String(15), nullable=False, server_default="SCHEDULED"),
        sa.Column("status", sa.String(15), nullable=False, server_default="RUNNING"),
        sa.Column("orders_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positions_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fills_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rogue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repaired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_reconciliation_runs_broker_started",
                    "reconciliation_runs", ["broker_name", "started_at"])
    op.create_index("idx_reconciliation_runs_status",
                    "reconciliation_runs", ["status"])

    op.create_table(
        "reconciliation_discrepancies",
        sa.Column("discrepancy_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(),
                  sa.ForeignKey("reconciliation_runs.run_id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("discrepancy_type", sa.String(30), nullable=False),
        sa.Column("order_id", sa.dialects.postgresql.UUID(as_uuid=True) if hasattr(sa.dialects, 'postgresql') else sa.String(36), nullable=True),
        sa.Column("broker_order_id", sa.String(50), nullable=True),
        sa.Column("oms_state", sa.String(50), nullable=True),
        sa.Column("broker_state", sa.String(50), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("repair_action", sa.String(50), nullable=True),
        sa.Column("repaired", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("repaired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_reconciliation_discrepancies_type",
                    "reconciliation_discrepancies", ["discrepancy_type", "created_at"])
    op.create_index("idx_reconciliation_discrepancies_repaired",
                    "reconciliation_discrepancies", ["repaired"])

    # Phase 20 — paper_trading_stats
    op.create_table(
        "paper_trading_stats",
        sa.Column("stat_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period_type", sa.String(10), nullable=False),  # DAILY/WEEKLY/MONTHLY
        sa.Column("period_label", sa.String(20), nullable=False),  # e.g. "2026-06-15"
        sa.Column("signals_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signals_approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signals_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_placed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positions_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positions_closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_pnl", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("win_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_drawdown", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("avg_hold_seconds", sa.Numeric(14, 2), nullable=True),
        sa.Column("avg_slippage_bps", sa.Numeric(10, 4), nullable=True),
        sa.Column("broker_latency_p50_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("broker_latency_p99_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("snapshot", _JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("period_type", "period_label", name="uq_paper_trading_period"),
    )
    op.create_index("idx_paper_trading_stats_period",
                    "paper_trading_stats", ["period_type", "period_label"])

    # Phase 21 — execution_analytics
    op.create_table(
        "execution_analytics",
        sa.Column("analytics_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.dialects.postgresql.UUID(as_uuid=True) if hasattr(sa.dialects, 'postgresql') else sa.String(36), nullable=True, index=True),
        sa.Column("signal_id", sa.dialects.postgresql.UUID(as_uuid=True) if hasattr(sa.dialects, 'postgresql') else sa.String(36), nullable=True),
        sa.Column("broker_name", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("signal_gen_latency_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("risk_eval_latency_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("broker_submit_latency_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("fill_latency_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_e2e_latency_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("fill_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("slippage_bps", sa.Numeric(10, 4), nullable=True),
        sa.Column("hold_seconds", sa.Numeric(14, 2), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(16, 2), nullable=True),
        sa.Column("trading_mode", sa.String(10), nullable=False, server_default="PAPER"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_execution_analytics_symbol_recorded",
                    "execution_analytics", ["symbol", "recorded_at"])
    op.create_index("idx_execution_analytics_broker",
                    "execution_analytics", ["broker_name", "recorded_at"])

    # Phase 26 — live_trading_ramp_up
    op.create_table(
        "live_trading_ramp_up",
        sa.Column("ramp_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("current_stage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stage_capital", sa.Numeric(16, 2), nullable=False, server_default="5000"),
        sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("lock_reason", sa.Text(), nullable=True),
        sa.Column("performance_snapshot", _JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("live_trading_ramp_up")
    op.drop_table("execution_analytics")
    op.drop_table("paper_trading_stats")
    op.drop_table("reconciliation_discrepancies")
    op.drop_table("reconciliation_runs")
