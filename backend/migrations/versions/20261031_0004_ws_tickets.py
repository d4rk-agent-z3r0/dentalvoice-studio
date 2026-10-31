# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""WebSocket admission tickets: single use, short lived, stored as a hash (ADR-0006).

Revision ID: f61a7e4e6e78
Revises: e9bff6a540d7
Create Date: 2026-10-31 12:50:59.063491+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f61a7e4e6e78"
down_revision: str | None = "e9bff6a540d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ws_tickets",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("clinic_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_ws_tickets_token_hash_format")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_ws_tickets_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "conversation_id"],
            ["conversations.clinic_id", "conversations.id"],
            name=op.f("fk_ws_tickets_clinic_id_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ws_tickets_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ws_tickets")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_ws_tickets_token_hash")),
    )
    op.create_index("ix_ws_tickets_expires_at", "ws_tickets", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ws_tickets_expires_at", table_name="ws_tickets")
    op.drop_table("ws_tickets")
