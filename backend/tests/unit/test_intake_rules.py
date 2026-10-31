# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from datetime import date

import pytest

from app.domain.enums import ConversationState, IntakeField, IntakeFieldStatus
from app.domain.spoken import find_email, find_phone, find_time, find_weekday_date
from app.services.intake.fields import FieldRejectedError, ValidationContext, validate_field
from app.services.intake.stages import (
    ALL_FIELDS,
    STAGE_FIELDS,
    intake_complete,
    missing_fields,
    stage_complete,
)

F = IntakeField
P = IntakeFieldStatus.PROVIDED
MONDAY = date(2026, 11, 2)
CTX = ValidationContext(today=MONDAY, service_codes=frozenset({"checkup", "hygiene_cleaning"}))


# --- spoken phrasing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It's ava dot lindqvist at example dot com.", "ava.lindqvist@example.com"),
        ("Please email me at elena dot fairbank at example dot net.", "elena.fairbank@example.net"),
        ("marcus dot b at example dot org", "marcus.b@example.org"),
        ("j underscore doe at example dot com", "j_doe@example.com"),
        ("write to someone@gmail.com", "someone@gmail.com"),  # found here, rejected by validation
        ("I'd rather not do email.", None),
        ("meet me at noon", None),
    ],
)
def test_find_email(text: str, expected: str | None) -> None:
    assert find_email(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("My number is 555-0101.", "555-0101"), ("call 555 0142", "555 0142"), ("no number", None)],
)
def test_find_phone(text: str, expected: str | None) -> None:
    assert find_phone(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Next Tuesday would be great", date(2026, 11, 3)),
        ("Thursday next week, in the afternoon", date(2026, 11, 5)),
        ("next Monday at nine thirty", date(2026, 11, 9)),  # never today
        ("Can we make that next Wednesday instead?", date(2026, 11, 4)),
        ("Monday or Tuesday", None),  # two days named: ambiguous
        ("whenever works", None),
    ],
)
def test_find_weekday_date(text: str, expected: date | None) -> None:
    assert find_weekday_date(text, MONDAY) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("around ten in the morning", "10:00"),
        ("in the afternoon. Maybe two o'clock?", "14:00"),
        ("next Monday at nine thirty", "09:30"),
        ("Around nine?", "09:00"),
        ("at 2:30 pm", "14:30"),
        ("10am works", "10:00"),
        ("about three", "15:00"),
        ("It's been about a year", None),
        ("My number is 555-0101", None),
    ],
)
def test_find_time(text: str, expected: str | None) -> None:
    assert find_time(text) == expected


# --- field validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        (F.FIRST_NAME, "  ava ", "Ava"),
        (F.LAST_NAME, "OKONKWO-HALE", "Okonkwo-Hale"),
        (F.LAST_NAME, "O'Neill", "O'Neill"),
        (F.PATIENT_TYPE, "Returning", "returning"),
        (F.PREFERRED_CONTACT_CHANNEL, "EMAIL", "email"),
        (F.EMAIL, "Ava.Lindqvist@Example.com", "ava.lindqvist@example.com"),
        (F.PHONE, "555 0101", "+1-555-0101"),
        (F.VISIT_REASON, " routine   cleaning ", "routine cleaning"),
        (F.REQUESTED_SERVICE, "Checkup", "checkup"),
        (F.PREFERRED_DATE, "2026-11-03", "2026-11-03"),
        (F.PREFERRED_TIME, "09:30", "09:30"),
    ],
)
def test_valid_values_are_normalised(field: IntakeField, raw: str, expected: str) -> None:
    assert validate_field(field, raw, CTX) == expected


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        (F.FIRST_NAME, "R2-D2"),
        (F.FIRST_NAME, ""),
        (F.PATIENT_TYPE, "vip"),
        (F.PREFERRED_CONTACT_CHANNEL, "carrier pigeon"),
        (F.EMAIL, "someone@gmail.com"),
        (F.PHONE, "212-867-5309"),
        (F.VISIT_REASON, "ok"),
        (F.VISIT_REASON, "call me on 555-0101"),
        (F.REQUESTED_SERVICE, "root_canal"),  # not offered by this clinic
        (F.PREFERRED_DATE, "next tuesday"),  # must already be resolved to a date
        (F.PREFERRED_DATE, "2026-11-02"),  # today
        (F.PREFERRED_DATE, "2026-10-30"),  # past
        (F.PREFERRED_DATE, "2027-03-01"),  # beyond the 60-day booking horizon
        (F.PREFERRED_TIME, "10am"),
        (F.PREFERRED_TIME, "22:00"),
    ],
)
def test_invalid_values_are_rejected_with_a_reason(field: IntakeField, raw: str) -> None:
    with pytest.raises(FieldRejectedError) as caught:
        validate_field(field, raw, CTX)
    assert caught.value.reason


# --- completeness ------------------------------------------------------------------------------


def _values(
    **overrides: tuple[str | None, IntakeFieldStatus],
) -> dict[IntakeField, tuple[str | None, IntakeFieldStatus]]:
    base: dict[IntakeField, tuple[str | None, IntakeFieldStatus]] = {
        F.FIRST_NAME: ("Ava", P),
        F.LAST_NAME: ("Lindqvist", P),
        F.PATIENT_TYPE: ("new", P),
        F.PREFERRED_CONTACT_CHANNEL: ("email", P),
        F.EMAIL: ("ava@example.com", P),
        F.PHONE: ("+1-555-0101", P),
        F.VISIT_REASON: ("cleaning", P),
        F.REQUESTED_SERVICE: ("hygiene_cleaning", P),
        F.PREFERRED_DATE: ("2026-11-03", P),
        F.PREFERRED_TIME: ("10:00", P),
    }
    base.update({IntakeField(k): v for k, v in overrides.items()})
    return base


def test_every_field_belongs_to_exactly_one_stage() -> None:
    owned = [f for fields in STAGE_FIELDS.values() for f in fields]
    assert sorted(owned) == sorted(F)
    assert set(ALL_FIELDS) == set(F)


def test_complete_intake_has_nothing_missing() -> None:
    assert missing_fields(_values()) == []
    assert intake_complete(_values())


def test_missing_fields_are_listed_in_conversation_order() -> None:
    values = _values()
    for gone in (F.PREFERRED_TIME, F.FIRST_NAME, F.EMAIL):
        del values[gone]
    assert missing_fields(values) == [F.FIRST_NAME, F.EMAIL, F.PREFERRED_TIME]


def test_declining_the_secondary_contact_is_allowed() -> None:
    values = _values(
        preferred_contact_channel=("phone", P), email=(None, IntakeFieldStatus.NOT_PROVIDED)
    )
    assert intake_complete(values)
    assert stage_complete(ConversationState.CONTACT_DETAILS, values)


def test_declining_the_preferred_channel_leaves_it_missing() -> None:
    values = _values(email=(None, IntakeFieldStatus.NOT_PROVIDED))  # channel is email
    assert missing_fields(values) == [F.EMAIL]
    assert not intake_complete(values)
