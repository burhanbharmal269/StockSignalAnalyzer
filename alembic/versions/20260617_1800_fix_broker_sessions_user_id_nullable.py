"""Fix broker_sessions.user_id NOT NULL constraint.

The Phase 4 migration created user_id as NOT NULL but the ORM model and
the BrokerSession entity never populate it — it's an unused FK placeholder.
Drop the NOT NULL constraint so sessions can be saved without a user_id.

Revision ID: 20260617_1800
Revises: 20260617_0900
"""

from __future__ import annotations

from alembic import op

revision = "20260617_1800"
down_revision = "20260617_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("broker_sessions", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("broker_sessions", "user_id", nullable=False)
