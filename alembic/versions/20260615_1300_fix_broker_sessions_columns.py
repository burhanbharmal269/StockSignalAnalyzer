"""Fix broker_sessions schema: add missing columns.

During launch verification, broker_sessions was missing api_key, user_id,
and encrypted_refresh_token columns that the ORM model requires.
This migration adds them formally so future deployments apply the fix
through the migration chain rather than ad-hoc ALTER TABLE.

Revision ID: 009_fix_broker_sessions
Revises: 008_phase19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_fix_broker_sessions"
down_revision: str = "008_phase19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    def _col_exists(table: str, column: str) -> bool:
        result = conn.execute(sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ), {"t": table, "c": column})
        return (result.scalar() or 0) > 0

    if not _col_exists("broker_sessions", "api_key"):
        op.add_column(
            "broker_sessions",
            sa.Column("api_key", sa.String(200), nullable=False, server_default=""),
        )

    if not _col_exists("broker_sessions", "user_id"):
        op.add_column(
            "broker_sessions",
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not _col_exists("broker_sessions", "encrypted_refresh_token"):
        op.add_column(
            "broker_sessions",
            sa.Column("encrypted_refresh_token", sa.Text, nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    def _col_exists(table: str, column: str) -> bool:
        result = conn.execute(sa.text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
        ), {"t": table, "c": column})
        return (result.scalar() or 0) > 0

    if _col_exists("broker_sessions", "encrypted_refresh_token"):
        op.drop_column("broker_sessions", "encrypted_refresh_token")

    if _col_exists("broker_sessions", "user_id"):
        op.drop_column("broker_sessions", "user_id")

    if _col_exists("broker_sessions", "api_key"):
        op.drop_column("broker_sessions", "api_key")
