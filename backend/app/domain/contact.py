# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Reserved, non-routable contact values.

Only RFC 2606 example domains and the North American fictional 555-0100..555-0199 range are valid
anywhere in this system. The same patterns back Pydantic validation and PostgreSQL CHECK
constraints, so a real address or number cannot be stored even by a buggy code path.
"""

import re

# PostgreSQL POSIX regex (used with the case-insensitive ~* operator) and the Python equivalent.
EMAIL_SQL_PATTERN = r"^[a-z0-9._%+-]+@example\.(com|org|net)$"
PHONE_SQL_PATTERN = r"^\+1-555-01[0-9]{2}$"

_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@example\.(?:com|org|net)", re.IGNORECASE)
_PHONE_DIGITS_RE = re.compile(r"(?:1)?55501(\d{2})")


class InvalidContactValueError(ValueError):
    """Raised for anything that is not a reserved example contact value."""


def normalise_email(value: str) -> str:
    candidate = value.strip().lower()
    if not _EMAIL_RE.fullmatch(candidate):
        raise InvalidContactValueError(
            "Email must use a reserved example domain (example.com, example.org or example.net)."
        )
    return candidate


def normalise_phone(value: str) -> str:
    """Accept common spellings of a fictional number and return ``+1-555-01xx``."""
    digits = re.sub(r"\D", "", value)
    match = _PHONE_DIGITS_RE.fullmatch(digits)
    if not match:
        raise InvalidContactValueError(
            "Phone must be a fictional number from 555-0100 to 555-0199."
        )
    return f"+1-555-01{match.group(1)}"
