"""Phase 12: Create signal_performance_stats table.

Revision ID: 003_phase12
Revises: 002_phase6
Create Date: 2026-06-13 09:00:00

Regular relational table (not a hypertable) — queried by fingerprint
and regime. Append-only: no updates or deletes permitted in application code.
Reference: docs/18_TIMESCALEDB_ARCHITECTURE.md §signal_performance_stats
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_phase12"
down_revision: Union[str, None] = "002_phase6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_performance_stats",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("signal_id", sa.String(36), nullable=False),
        sa.Column("instrument", sa.String(30), nullable=False),
        sa.Column("instrument_class", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("regime_at_signal", sa.String(30), nullable=False),
        sa.Column("score_bucket", sa.String(10), nullable=False),
        sa.Column("vix_bucket", sa.String(10), nullable=False),
        sa.Column(
            "top_2_components",
            postgresql.ARRAY(sa.String(50)),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("outcome", sa.String(15), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("exit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("pnl_bps", sa.Integer, nullable=False),
        sa.Column("hold_duration_minutes", sa.Integer, nullable=False),
        sa.Column("dte_at_signal", sa.Integer, nullable=False),
        sa.Column("confidence_calibration_error", sa.Numeric(6, 3), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_index(
        "idx_spstats_fingerprint",
        "signal_performance_stats",
        ["fingerprint", "recorded_at"],
    )
    op.create_index(
        "idx_spstats_regime_direction",
        "signal_performance_stats",
        ["regime_at_signal", "direction", "instrument_class", "recorded_at"],
    )
    op.create_index(
        "idx_spstats_instrument",
        "signal_performance_stats",
        ["instrument", "recorded_at"],
    )
    op.create_index(
        "idx_spstats_outcome",
        "signal_performance_stats",
        ["outcome", "regime_at_signal"],
    )


def downgrade() -> None:
    op.drop_index("idx_spstats_outcome", table_name="signal_performance_stats")
    op.drop_index("idx_spstats_instrument", table_name="signal_performance_stats")
    op.drop_index("idx_spstats_regime_direction", table_name="signal_performance_stats")
    op.drop_index("idx_spstats_fingerprint", table_name="signal_performance_stats")
    op.drop_table("signal_performance_stats")
