# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Read the violated constraint from a database error, so services can map it to a domain error."""

from sqlalchemy.exc import DBAPIError


def violated_constraint(error: DBAPIError) -> str | None:
    """Name of the constraint behind an asyncpg integrity error, if there is one."""
    cause = getattr(error.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return name if isinstance(name, str) else None
