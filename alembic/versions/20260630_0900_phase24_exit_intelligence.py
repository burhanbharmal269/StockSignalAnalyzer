"""Phase 24 — Exit Intelligence, Target Calibration & Option Efficiency.

Adds analytics columns to signal_analytics for:
  Section 1  — Expected Move Engine
  Section 2  — Dynamic Target Recommendation
  Section 3  — Target Realism Analysis
  Section 4  — Expired Trade Intelligence
  Section 5  — Option Efficiency Engine
  Section 8  — Holding Time Analysis (time_in_profit, time_in_loss, time_near_target)

Revision ID: 20260630_0900
Revises: 20260627_1100
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260630_0900"
down_revision = "20260627_1100"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── Section 1: Expected Move Engine ────────────────────────────────────
    op.add_column("signal_analytics", sa.Column("expected_underlying_move_pct", sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("expected_option_move_pct",     sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("expected_holding_minutes",     sa.Integer(),      nullable=True))
    op.add_column("signal_analytics", sa.Column("reach_prob_json",              sa.Text(),         nullable=True))

    # ── Section 2: Dynamic Target Recommendation ────────────────────────────
    op.add_column("signal_analytics", sa.Column("recommended_target_pct",   sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("recommended_stop_pct",     sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("recommended_holding_minutes", sa.Integer(), nullable=True))
    op.add_column("signal_analytics", sa.Column("target_confidence",        sa.Numeric(5, 2), nullable=True))

    # ── Section 3: Target Realism ───────────────────────────────────────────
    op.add_column("signal_analytics", sa.Column("configured_target_pct", sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("configured_sl_pct",     sa.Numeric(8, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("target_realism_pct",    sa.Numeric(8, 4), nullable=True))

    # ── Section 4: Expired Trade Intelligence ──────────────────────────────
    op.add_column("signal_analytics", sa.Column("expiry_reason",       sa.String(40), nullable=True))
    op.add_column("signal_analytics", sa.Column("expiry_snapshot_json", sa.Text(),    nullable=True))

    # ── Section 5: Option Efficiency Engine ────────────────────────────────
    op.add_column("signal_analytics", sa.Column("option_efficiency_score", sa.Numeric(7, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("delta_efficiency",        sa.Numeric(7, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("gamma_efficiency",        sa.Numeric(7, 4), nullable=True))
    op.add_column("signal_analytics", sa.Column("vega_impact",             sa.Numeric(7, 4), nullable=True))

    # ── Section 8: Holding Time Analysis ───────────────────────────────────
    op.add_column("signal_analytics", sa.Column("time_in_profit_minutes",   sa.Integer(), nullable=True))
    op.add_column("signal_analytics", sa.Column("time_in_loss_minutes",     sa.Integer(), nullable=True))
    op.add_column("signal_analytics", sa.Column("time_near_target_minutes", sa.Integer(), nullable=True))

    # Index for expiry reason distribution queries
    op.create_index("idx_sa_expiry_reason", "signal_analytics", ["expiry_reason"],
                    postgresql_where=sa.text("expiry_reason IS NOT NULL"))
    op.create_index("idx_sa_target_realism", "signal_analytics", ["target_realism_pct"],
                    postgresql_where=sa.text("target_realism_pct IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("idx_sa_target_realism", table_name="signal_analytics")
    op.drop_index("idx_sa_expiry_reason",  table_name="signal_analytics")

    for col in [
        "time_near_target_minutes", "time_in_loss_minutes", "time_in_profit_minutes",
        "vega_impact", "gamma_efficiency", "delta_efficiency", "option_efficiency_score",
        "expiry_snapshot_json", "expiry_reason",
        "target_realism_pct", "configured_sl_pct", "configured_target_pct",
        "target_confidence", "recommended_holding_minutes", "recommended_stop_pct", "recommended_target_pct",
        "reach_prob_json", "expected_holding_minutes", "expected_option_move_pct", "expected_underlying_move_pct",
    ]:
        op.drop_column("signal_analytics", col)
