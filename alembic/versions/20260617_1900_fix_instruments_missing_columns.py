"""Add missing columns to instruments table.

segment, underlying_symbol, option_type, isin, display_symbol were added
to the ORM model but never added to the table via migration.

Revision ID: 20260617_1900
Revises: 20260617_1800
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260617_1900"
down_revision = "20260617_1800"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=:t AND column_name=:c"
    ), {"t": table, "c": col})
    return result.fetchone() is not None


def upgrade() -> None:
    if not _col_exists("instruments", "segment"):
        op.add_column("instruments", sa.Column("segment", sa.String(20), nullable=False, server_default=""))
    if not _col_exists("instruments", "underlying_symbol"):
        op.add_column("instruments", sa.Column("underlying_symbol", sa.String(30), nullable=True))
    if not _col_exists("instruments", "option_type"):
        op.add_column("instruments", sa.Column("option_type", sa.String(2), nullable=True))
    if not _col_exists("instruments", "isin"):
        op.add_column("instruments", sa.Column("isin", sa.String(12), nullable=True))
    if not _col_exists("instruments", "display_symbol"):
        op.add_column("instruments", sa.Column("display_symbol", sa.String(100), nullable=False, server_default=""))


def downgrade() -> None:
    for col in ["display_symbol", "isin", "option_type", "underlying_symbol", "segment"]:
        if _col_exists("instruments", col):
            op.drop_column("instruments", col)
