"""Phase 6: Add auth columns — force_change to users table.

Revision ID: 002_phase6
Revises: 001_phase4
Create Date: 2026-06-12 08:00:00

Adds:
  - users.force_change (BOOLEAN, NOT NULL, DEFAULT FALSE) — first-run flag (Doc 23 §2).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_phase6"
down_revision: Union[str, None] = "001_phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("force_change", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "force_change")
