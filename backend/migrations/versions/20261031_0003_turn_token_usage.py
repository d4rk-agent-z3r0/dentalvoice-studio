# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Conversation turns: token usage and attempt count reported by the conversation provider.

Revision ID: e9bff6a540d7
Revises: 7c1e2a9d4b10
Create Date: 2026-10-31 11:37:10+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9bff6a540d7"
down_revision: str | None = "7c1e2a9d4b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_turns", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_turns", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_turns", sa.Column("llm_attempts", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "usage_non_negative",
        "conversation_turns",
        "coalesce(prompt_tokens, 0) >= 0 AND coalesce(output_tokens, 0) >= 0 "
        "AND coalesce(llm_attempts, 1) >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_conversation_turns_usage_non_negative"), "conversation_turns", type_="check"
    )
    op.drop_column("conversation_turns", "llm_attempts")
    op.drop_column("conversation_turns", "output_tokens")
    op.drop_column("conversation_turns", "prompt_tokens")
