"""Add user_name to broker_sessions.

Revision ID: 20260616_1200
Revises: 20260616_1000
Create Date: 2026-06-16 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260616_1200"
down_revision = "010_phase28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broker_sessions",
        sa.Column("user_name", sa.String(200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("broker_sessions", "user_name")
