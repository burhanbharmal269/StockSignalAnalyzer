"""Add option contract fields to signal_analytics table.

Adds option_type, option_strike, option_expiry, option_symbol,
option_entry, option_sl, option_target so every F&O signal
carries a specific CE/PE contract recommendation.

Revision ID: 20260618_1000
Revises: 20260617_1900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260618_1000"
down_revision = "20260617_1900"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    for col, typ in [
        ("option_type",   sa.String(2)),
        ("option_strike", sa.Numeric(10, 2)),
        ("option_expiry", sa.Date()),
        ("option_symbol", sa.String(30)),
        ("option_entry",  sa.Numeric(10, 2)),
        ("option_sl",     sa.Numeric(10, 2)),
        ("option_target", sa.Numeric(10, 2)),
    ]:
        if not _col_exists("signal_analytics", col):
            op.add_column("signal_analytics", sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for col in [
        "option_type", "option_strike", "option_expiry", "option_symbol",
        "option_entry", "option_sl", "option_target",
    ]:
        if _col_exists("signal_analytics", col):
            op.drop_column("signal_analytics", col)
