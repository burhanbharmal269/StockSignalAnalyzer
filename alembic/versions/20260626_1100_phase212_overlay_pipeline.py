"""Phase 21.2 — Overlay Pipeline decision trace columns.

Adds three columns to signal_analytics for full audit reproducibility:
  decision_trace_json  TEXT           — ordered overlay steps with before/after values
  decision_version     VARCHAR(20)    — pipeline version at time of signal (e.g. "21.2")
  overlay_version      VARCHAR(20)    — overlay config version (e.g. "1.0")

These columns allow post-hoc replay: given any stored signal you can reconstruct
exactly which overlay adjustments were applied and why, without querying live state.

Revision ID: 20260626_1100
Revises: 20260626_1000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_1100"
down_revision = "20260626_1000"
branch_labels = None
depends_on = None


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
    new_cols = [
        ("decision_trace_json", sa.Text()),
        ("decision_version",    sa.String(20)),
        ("overlay_version",     sa.String(20)),
    ]
    for col_name, col_type in new_cols:
        if not _col_exists("signal_analytics", col_name):
            op.add_column("signal_analytics", sa.Column(col_name, col_type, nullable=True))

    if not _index_exists("ix_signal_analytics_decision_version"):
        op.create_index(
            "ix_signal_analytics_decision_version",
            "signal_analytics",
            ["decision_version"],
        )


def downgrade() -> None:
    if _index_exists("ix_signal_analytics_decision_version"):
        op.drop_index("ix_signal_analytics_decision_version", table_name="signal_analytics")
    for col_name in ("overlay_version", "decision_version", "decision_trace_json"):
        if _col_exists("signal_analytics", col_name):
            op.drop_column("signal_analytics", col_name)
