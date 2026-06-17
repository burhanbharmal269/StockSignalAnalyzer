"""Phase 18: Production hardening tables.

Adds:
  - broker_order_mapping   (internal ↔ broker order correlation + retry tracking)
  - idempotency_keys       (persistent DB-level idempotency — supplements Redis cache)
  - audit_logs columns     (old_value, new_value, entity_type, entity_id, metadata)

Revision ID: 007_phase18
Revises: 006_phase17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_phase18"
down_revision: str = "006_phase17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # broker_order_mapping — maps internal OMS order ↔ broker order IDs
    # -------------------------------------------------------------------------
    op.create_table(
        "broker_order_mapping",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("internal_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("broker_order_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("broker_name", sa.String(30), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_bom_internal_order_id",
        "broker_order_mapping",
        ["internal_order_id"],
        unique=True,
    )
    op.create_index(
        "idx_bom_broker_order_id",
        "broker_order_mapping",
        ["broker_order_id"],
    )
    op.create_index(
        "idx_bom_status",
        "broker_order_mapping",
        ["status"],
    )

    # -------------------------------------------------------------------------
    # idempotency_keys — DB-level idempotency (complements Redis cache)
    # -------------------------------------------------------------------------
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_payload", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_idempotency_key", "idempotency_keys", ["key"], unique=True)
    op.create_index("idx_idempotency_expires_at", "idempotency_keys", ["expires_at"])

    # -------------------------------------------------------------------------
    # audit_logs — extend existing table with new columns
    # -------------------------------------------------------------------------
    op.add_column(
        "audit_logs",
        sa.Column("entity_type", sa.String(50), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("entity_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("old_value", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("new_value", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "audit_logs",
        sa.Column("metadata", postgresql.JSONB, nullable=True),
    )
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"])
    op.create_index("idx_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("idx_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_user_id", "audit_logs")
    op.drop_index("idx_audit_logs_entity", "audit_logs")
    op.drop_index("idx_audit_logs_action", "audit_logs")
    op.drop_column("audit_logs", "metadata")
    op.drop_column("audit_logs", "new_value")
    op.drop_column("audit_logs", "old_value")
    op.drop_column("audit_logs", "entity_id")
    op.drop_column("audit_logs", "entity_type")

    op.drop_index("idx_idempotency_expires_at", "idempotency_keys")
    op.drop_index("idx_idempotency_key", "idempotency_keys")
    op.drop_table("idempotency_keys")

    op.drop_index("idx_bom_status", "broker_order_mapping")
    op.drop_index("idx_bom_broker_order_id", "broker_order_mapping")
    op.drop_index("idx_bom_internal_order_id", "broker_order_mapping")
    op.drop_table("broker_order_mapping")
