"""Phase 20.6 — signal_replay_events table for Trade Replay Engine.

One row per lifecycle event per signal. Records market state at each
key moment: GENERATED, ENTRY, MFE_PEAK, MAE_TROUGH, EXIT, EXPIRED.

For historical backfill, TradeReplayService creates:
  GENERATED — from signal_analytics.created_at + all component data
  EXIT       — from outcome + timing columns

MFE_PEAK and MAE_TROUGH timestamps require real-time candle tracking
(SignalOutcomeTrackerService) and are populated when available.

Revision ID: 20260620_1000
Revises: 20260620_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision      = "20260620_1000"
down_revision = "20260620_0900"
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
    if _table_exists("signal_replay_events"):
        return

    op.create_table(
        "signal_replay_events",
        sa.Column("id",              sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("signal_id",       sa.String(36),   nullable=False),
        sa.Column("event_type",      sa.String(20),   nullable=False),  # GENERATED/ENTRY/MFE_PEAK/MAE_TROUGH/EXIT/EXPIRED
        sa.Column("event_sequence",  sa.Integer(),    nullable=False),   # ordering within signal

        # When this event occurred
        sa.Column("event_time",      sa.DateTime(timezone=True), nullable=True),

        # Underlying / option state at this event
        sa.Column("underlying_price",  sa.Numeric(12, 2), nullable=True),
        sa.Column("option_premium",    sa.Numeric(10, 2), nullable=True),
        sa.Column("iv_percentile",     sa.Numeric(5,  2), nullable=True),
        sa.Column("vwap_distance_pct", sa.Numeric(8,  4), nullable=True),
        sa.Column("oi_change_pct",     sa.Numeric(8,  4), nullable=True),
        sa.Column("volume_ratio",      sa.Numeric(6,  3), nullable=True),
        sa.Column("adx",               sa.Numeric(5,  2), nullable=True),
        sa.Column("mtf_alignment",     sa.String(10),      nullable=True),
        sa.Column("regime",            sa.String(30),      nullable=True),

        # Signal state at this event
        sa.Column("adjusted_score",  sa.Numeric(5, 2), nullable=True),
        sa.Column("confidence",      sa.Numeric(5, 2), nullable=True),
        sa.Column("pnl_pct_at_event", sa.Numeric(8, 4), nullable=True),  # running P&L at this moment

        # Flexible extra context
        sa.Column("event_data_json", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    op.create_index("idx_sre_signal_id",   "signal_replay_events", ["signal_id"])
    op.create_index("idx_sre_signal_seq",  "signal_replay_events", ["signal_id", "event_sequence"])
    op.create_index("idx_sre_event_type",  "signal_replay_events", ["event_type", "created_at"])


def downgrade() -> None:
    if _table_exists("signal_replay_events"):
        op.drop_index("idx_sre_event_type",  table_name="signal_replay_events")
        op.drop_index("idx_sre_signal_seq",  table_name="signal_replay_events")
        op.drop_index("idx_sre_signal_id",   table_name="signal_replay_events")
        op.drop_table("signal_replay_events")
