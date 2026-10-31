# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Intake drafts: record fields the caller explicitly declined (status ``not_provided``).

A declined field is different from one that was never mentioned: the receptionist must not ask
again, and the snapshot must show the value as deliberately absent. ``not_provided`` rows carry no
value and count as the field's live row.

Revision ID: 7c1e2a9d4b10
Revises: 293745f95565
Create Date: 2026-10-31 12:30:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e2a9d4b10"
down_revision: str | None = "293745f95565"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_CHECK = "ck_intake_drafts_status_valid"
_LIVE_INDEX = "uq_intake_drafts_live_field"

_OLD_STATUSES = "'provided', 'needs_confirmation', 'confirmed', 'rejected', 'superseded'"
_NEW_STATUSES = (
    "'provided', 'not_provided', 'needs_confirmation', 'confirmed', 'rejected', 'superseded'"
)
_OLD_LIVE = "status IN ('provided', 'needs_confirmation', 'confirmed')"
_NEW_LIVE = "status IN ('confirmed', 'needs_confirmation', 'not_provided', 'provided')"


def _replace_live_index(where: str) -> None:
    op.drop_index(_LIVE_INDEX, table_name="intake_drafts")
    op.create_index(
        _LIVE_INDEX,
        "intake_drafts",
        ["conversation_id", "field"],
        unique=True,
        postgresql_where=sa.text(where),
    )


def upgrade() -> None:
    op.drop_constraint(op.f(_STATUS_CHECK), "intake_drafts", type_="check")
    op.create_check_constraint("status_valid", "intake_drafts", f"status IN ({_NEW_STATUSES})")
    op.create_check_constraint(
        "value_presence", "intake_drafts", "(status = 'not_provided') = (value IS NULL)"
    )
    _replace_live_index(_NEW_LIVE)


def downgrade() -> None:
    # Declined fields have no representation in the old schema; they become "never mentioned".
    op.execute("DELETE FROM intake_drafts WHERE status = 'not_provided'")
    _replace_live_index(_OLD_LIVE)
    op.drop_constraint(op.f("ck_intake_drafts_value_presence"), "intake_drafts", type_="check")
    op.drop_constraint(op.f(_STATUS_CHECK), "intake_drafts", type_="check")
    op.create_check_constraint("status_valid", "intake_drafts", f"status IN ({_OLD_STATUSES})")
