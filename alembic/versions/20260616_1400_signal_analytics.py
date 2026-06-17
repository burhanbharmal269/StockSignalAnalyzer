"""Create signal_analytics table for always-on signal intelligence tracking.

Revision ID: 20260616_1400
Revises: 20260616_1200
Create Date: 2026-06-16 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_1400"
down_revision = "20260616_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_analytics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.String(36), nullable=True),

        # Identity
        sa.Column("ticker", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("strategy_type", sa.String(30), nullable=False),
        sa.Column("regime", sa.String(30), nullable=False),
        sa.Column("sector", sa.String(50), nullable=True),
        sa.Column("is_index", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("execution_mode", sa.String(20), nullable=False, server_default="MANUAL"),

        # Signal levels
        sa.Column("entry_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dte", sa.Integer(), nullable=True),

        # Composite scores
        sa.Column("raw_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("adjusted_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),

        # Component score breakdown
        sa.Column("trend_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("volume_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("vwap_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("oi_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("iv_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("option_chain_score", sa.Numeric(5, 2), nullable=True),

        # Technical context
        sa.Column("adx_at_signal", sa.Numeric(5, 2), nullable=True),
        sa.Column("volume_ratio_at_signal", sa.Numeric(6, 3), nullable=True),
        sa.Column("rsi_at_signal", sa.Numeric(5, 2), nullable=True),

        # Acceptance tracking
        sa.Column("was_accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("rejection_reason", sa.String(50), nullable=True),

        # Outcome tracking
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("target_hit", sa.Boolean(), nullable=True),
        sa.Column("stop_hit", sa.Boolean(), nullable=True),
        sa.Column("mfe_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("mae_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("return_1h_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("return_1d_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("return_5d_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("time_to_target_minutes", sa.Integer(), nullable=True),
        sa.Column("time_to_stop_minutes", sa.Integer(), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("outcome_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_sa_signal_id", "signal_analytics", ["signal_id"])
    op.create_index("idx_sa_ticker_created", "signal_analytics", ["ticker", "created_at"])
    op.create_index("idx_sa_strategy_created", "signal_analytics", ["strategy_type", "created_at"])
    op.create_index("idx_sa_direction_regime", "signal_analytics", ["direction", "regime"])
    op.create_index("idx_sa_outcome", "signal_analytics", ["outcome", "strategy_type"])
    op.create_index("idx_sa_accepted", "signal_analytics", ["was_accepted", "created_at"])
    op.create_index("idx_sa_sector", "signal_analytics", ["sector"])


def downgrade() -> None:
    op.drop_table("signal_analytics")
