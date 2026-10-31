# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Field-level validation and normalisation for intake values.

Every proposed value, from a model or anywhere else, passes through ``validate_field``. A value
that fails is recorded as rejected with a reason and never applied. Nothing here guesses: an
ambiguous or partial value is rejected, not completed.
"""

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

from app.domain.contact import InvalidContactValueError, normalise_email, normalise_phone
from app.domain.enums import ContactChannel, IntakeField, PatientType

_NAME_RE = re.compile(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*")
_TIME_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_CONTACT_LIKE_RE = re.compile(r"@|\d{3}[\s.-]?\d{4}")

EARLIEST_TIME = time(7, 0)
LATEST_TIME = time(19, 0)


class FieldRejectedError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidationContext:
    today: date  # in the clinic's timezone
    service_codes: frozenset[str]
    booking_horizon_days: int = 60


def _name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not 1 <= len(cleaned) <= 80 or not _NAME_RE.fullmatch(cleaned):
        raise FieldRejectedError("Names may contain letters, spaces, hyphens and apostrophes only.")
    if cleaned.islower() or cleaned.isupper():
        # Transcripts often arrive in one case; restore conventional capitalisation per part.
        cleaned = re.sub(r"[^\W\d_]+", lambda m: m.group(0).capitalize(), cleaned.lower())
    return cleaned


def _choice(value: str, allowed: type[ContactChannel] | type[PatientType]) -> str:
    candidate = value.strip().lower()
    if candidate not in {member.value for member in allowed}:
        options = ", ".join(member.value for member in allowed)
        raise FieldRejectedError(f"Expected one of: {options}.")
    return candidate


def _visit_reason(value: str) -> str:
    cleaned = " ".join(value.split())
    if not 3 <= len(cleaned) <= 200:
        raise FieldRejectedError("Visit reason must be 3 to 200 characters.")
    if _CONTACT_LIKE_RE.search(cleaned):
        raise FieldRejectedError("Visit reason must not contain contact details.")
    return cleaned


def _service(value: str, ctx: ValidationContext) -> str:
    code = value.strip().lower()
    if code not in ctx.service_codes:
        raise FieldRejectedError("Not a service offered by this clinic.")
    return code


def _date(value: str, ctx: ValidationContext) -> str:
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as error:
        raise FieldRejectedError("Preferred date must be an ISO date (YYYY-MM-DD).") from error
    if parsed <= ctx.today:
        raise FieldRejectedError("Preferred date must be after today.")
    if parsed > ctx.today + timedelta(days=ctx.booking_horizon_days):
        raise FieldRejectedError(f"Preferred date must be within {ctx.booking_horizon_days} days.")
    return parsed.isoformat()


def _time(value: str) -> str:
    match = _TIME_RE.fullmatch(value.strip())
    if not match:
        raise FieldRejectedError("Preferred time must be 24-hour HH:MM.")
    parsed = time(int(match.group(1)), int(match.group(2)))
    if not EARLIEST_TIME <= parsed <= LATEST_TIME:
        raise FieldRejectedError("Preferred time must be between 07:00 and 19:00.")
    return parsed.strftime("%H:%M")


def validate_field(field: IntakeField, value: str, ctx: ValidationContext) -> str:
    """Return the normalised value or raise ``FieldRejectedError`` with a reason."""
    try:
        match field:
            case IntakeField.FIRST_NAME | IntakeField.LAST_NAME:
                return _name(value)
            case IntakeField.PATIENT_TYPE:
                return _choice(value, PatientType)
            case IntakeField.PREFERRED_CONTACT_CHANNEL:
                return _choice(value, ContactChannel)
            case IntakeField.EMAIL:
                return normalise_email(value)
            case IntakeField.PHONE:
                return normalise_phone(value)
            case IntakeField.VISIT_REASON:
                return _visit_reason(value)
            case IntakeField.REQUESTED_SERVICE:
                return _service(value, ctx)
            case IntakeField.PREFERRED_DATE:
                return _date(value, ctx)
            case IntakeField.PREFERRED_TIME:
                return _time(value)
    except InvalidContactValueError as error:
        raise FieldRejectedError(str(error)) from error


# Only contact values can be declined; everything else is needed to complete onboarding.
DECLINABLE_FIELDS = frozenset({IntakeField.EMAIL, IntakeField.PHONE})
