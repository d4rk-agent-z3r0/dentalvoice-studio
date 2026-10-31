# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Which fields each conversation stage owns, and when a stage is complete.

Pure functions over the live intake values, so completeness is computed from data, never taken
from a model's ``missing_fields``.
"""

from collections.abc import Mapping

from app.domain.enums import ContactChannel, ConversationState, IntakeField, IntakeFieldStatus

S = ConversationState
F = IntakeField

STAGE_FIELDS: dict[ConversationState, tuple[IntakeField, ...]] = {
    S.INTRODUCTION: (F.PATIENT_TYPE,),
    S.IDENTITY_COLLECTION: (F.FIRST_NAME, F.LAST_NAME),
    S.CONTACT_DETAILS: (F.PREFERRED_CONTACT_CHANNEL, F.EMAIL, F.PHONE),
    S.VISIT_REASON: (F.VISIT_REASON, F.REQUESTED_SERVICE),
    S.APPOINTMENT_PREFERENCES: (F.PREFERRED_DATE, F.PREFERRED_TIME),
}

FIELD_STAGE: dict[IntakeField, ConversationState] = {
    field: stage for stage, fields in STAGE_FIELDS.items() for field in fields
}

ALL_FIELDS: tuple[IntakeField, ...] = tuple(FIELD_STAGE)

# A live value: (normalised value or None when declined, status).
LiveValues = Mapping[IntakeField, tuple[str | None, IntakeFieldStatus]]


def _has_value(values: LiveValues, field: IntakeField) -> bool:
    entry = values.get(field)
    return entry is not None and entry[0] is not None


def _resolved(values: LiveValues, field: IntakeField) -> bool:
    """Provided, or explicitly declined."""
    return field in values


def missing_fields(values: LiveValues) -> list[IntakeField]:
    """Fields still needed, in conversation order. Declined contact values are not missing,
    except the one the caller chose as their preferred channel."""
    missing = [field for field in ALL_FIELDS if not _resolved(values, field)]
    channel = values.get(F.PREFERRED_CONTACT_CHANNEL)
    if channel is not None and channel[0] is not None:
        preferred = F.EMAIL if channel[0] == ContactChannel.EMAIL else F.PHONE
        if preferred in values and not _has_value(values, preferred):
            missing.append(preferred)  # declined the very channel they asked to be contacted on
    return sorted(set(missing), key=ALL_FIELDS.index)


def stage_complete(stage: ConversationState, values: LiveValues) -> bool:
    gaps = set(missing_fields(values))
    return not gaps.intersection(STAGE_FIELDS.get(stage, ()))


def intake_complete(values: LiveValues) -> bool:
    return not missing_fields(values)
