"""signal_analytics: add current_return_pct, regime index

Revision ID: 20260617_0900
Revises: 20260616_1400
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260617_0900"
down_revision = "20260616_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signal_analytics",
        sa.Column("current_return_pct", sa.Numeric(8, 4), nullable=True),
    )
    # Index to accelerate regime-performance queries
    op.create_index(
        "idx_sa_regime_strategy",
        "signal_analytics",
        ["regime", "strategy_type", "outcome"],
    )
    # Index for symbol leaderboard
    op.create_index(
        "idx_sa_ticker_outcome",
        "signal_analytics",
        ["ticker", "outcome", "was_accepted"],
    )
    # Index for sector leaderboard
    op.create_index(
        "idx_sa_sector_outcome",
        "signal_analytics",
        ["sector", "outcome", "was_accepted"],
    )


def downgrade() -> None:
    op.drop_index("idx_sa_sector_outcome", table_name="signal_analytics")
    op.drop_index("idx_sa_ticker_outcome", table_name="signal_analytics")
    op.drop_index("idx_sa_regime_strategy", table_name="signal_analytics")
    op.drop_column("signal_analytics", "current_return_pct")
