# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import re
import time
import uuid

import pytest
from pydantic import ValidationError

from app.core.ids import uuid7
from app.domain.contact import (
    EMAIL_SQL_PATTERN,
    PHONE_SQL_PATTERN,
    InvalidContactValueError,
    normalise_email,
    normalise_phone,
)
from app.domain.enums import ContactChannel, PatientType
from app.schemas.patient import PatientCreate, PatientUpdate


def test_uuid7_has_version_7_and_rfc_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_time_ordered() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first < second


def test_uuid7_embeds_current_unix_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= value.int >> 80 <= after


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ava.Patel@Example.com", "ava.patel@example.com"),
        ("  j.doe+demo@example.org ", "j.doe+demo@example.org"),
        ("x@example.net", "x@example.net"),
    ],
)
def test_reserved_emails_are_normalised(raw: str, expected: str) -> None:
    assert normalise_email(raw) == expected
    assert re.fullmatch(EMAIL_SQL_PATTERN.strip("^$"), expected)


@pytest.mark.parametrize(
    "raw", ["someone@gmail.com", "a@example.co", "a@sub.example.com", "a@exampleXcom", "", "a"]
)
def test_routable_emails_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidContactValueError):
        normalise_email(raw)


@pytest.mark.parametrize(
    "raw", ["555-0142", "(555) 0142", "+1 555 0142", "1-555-0142", "555.01.42", "5550142"]
)
def test_fictional_phone_spellings_normalise_to_canonical_form(raw: str) -> None:
    assert normalise_phone(raw) == "+1-555-0142"
    assert re.fullmatch(PHONE_SQL_PATTERN.strip("^$"), "+1-555-0142")


@pytest.mark.parametrize("raw", ["555-0200", "555-0099", "212-555-0142", "+44 20 7946 0958", ""])
def test_real_or_out_of_range_numbers_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidContactValueError):
        normalise_phone(raw)


def test_patient_create_normalises_contact_values() -> None:
    patient = PatientCreate(
        first_name=" Ava ",
        last_name="Patel",
        email="AVA@EXAMPLE.COM",
        phone="555 0142",
        preferred_contact_channel=ContactChannel.EMAIL,
        patient_type=PatientType.NEW,
    )
    assert (patient.first_name, patient.email, patient.phone) == (
        "Ava",
        "ava@example.com",
        "+1-555-0142",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": None, "phone": None},
        {"email": None, "preferred_contact_channel": ContactChannel.EMAIL},
        {"phone": None, "preferred_contact_channel": ContactChannel.PHONE},
        {"email": "real.person@gmail.com"},
        {"first_name": ""},
        {"unexpected": "field"},
    ],
)
def test_patient_create_rejects_invalid_input(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "first_name": "Ava",
        "last_name": "Patel",
        "email": "ava@example.com",
        "phone": "555-0142",
        "patient_type": PatientType.NEW,
        **overrides,
    }
    with pytest.raises(ValidationError):
        PatientCreate.model_validate(values)


def test_patient_update_tracks_only_fields_that_were_sent() -> None:
    changes = PatientUpdate(phone="555-0150")
    assert changes.model_dump(exclude_unset=True) == {"phone": "+1-555-0150"}
