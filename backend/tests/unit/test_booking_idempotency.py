# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Canonical request hashing and idempotency-key rules."""

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.booking import AppointmentCreate
from app.services.booking.idempotency import (
    canonical_json,
    is_client_key,
    request_hash,
    reschedule_key,
)

PATIENT = "0192f0a8-0000-7000-8000-000000000001"
TYPE = "0192f0a8-0000-7000-8000-000000000002"
DENTIST = "0192f0a8-0000-7000-8000-000000000003"


def body(**overrides: object) -> dict[str, object]:
    return {
        "patient_id": PATIENT,
        "appointment_type_id": TYPE,
        "dentist_id": DENTIST,
        "starts_at": "2030-01-07T09:00:00Z",
        **overrides,
    }


def digest(raw: dict[str, object]) -> str:
    return request_hash(AppointmentCreate.model_validate(raw).model_dump(mode="json"))


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, "é"], "c": None}) == '{"a":[1,"é"],"b":1,"c":null}'


def test_hash_is_sha256_of_the_canonical_normalised_body() -> None:
    expected_text = (
        f'{{"appointment_type_id":"{TYPE}","conversation_id":null,"dentist_id":"{DENTIST}",'
        f'"patient_id":"{PATIENT}","starts_at":"2030-01-07T09:00:00Z"}}'
    )
    assert digest(body()) == hashlib.sha256(expected_text.encode()).hexdigest()


@pytest.mark.parametrize(
    "variant",
    [
        body(starts_at="2030-01-07T10:00:00+01:00"),  # same instant, another offset
        body(starts_at="2030-01-07T04:00:00-05:00"),
        body(starts_at="2030-01-07T09:00:00.000+00:00"),
        body(conversation_id=None),  # explicit null equals absent
        dict(reversed(list(body().items()))),  # key order is irrelevant
        body(patient_id=PATIENT.upper()),  # UUID spelling is irrelevant
    ],
)
def test_equivalent_requests_hash_the_same(variant: dict[str, object]) -> None:
    assert digest(variant) == digest(body())


@pytest.mark.parametrize(
    "variant",
    [
        body(starts_at="2030-01-07T09:15:00Z"),
        body(patient_id=str(uuid.UUID(int=9))),
        body(dentist_id=str(uuid.UUID(int=9))),
        body(appointment_type_id=str(uuid.UUID(int=9))),
        body(conversation_id=str(uuid.UUID(int=9))),
    ],
)
def test_different_requests_hash_differently(variant: dict[str, object]) -> None:
    assert digest(variant) != digest(body())


@pytest.mark.parametrize(
    "raw",
    [
        body(starts_at="2030-01-07T09:00:00"),  # naive: which timezone?
        body(clinic_id=str(uuid.uuid4())),  # the clinic only ever comes from the token
        {k: v for k, v in body().items() if k != "dentist_id"},
    ],
)
def test_ambiguous_or_unexpected_bodies_are_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AppointmentCreate.model_validate(raw)


@pytest.mark.parametrize(
    ("key", "valid"),
    [
        ("abcdefgh", True),
        (uuid.uuid4().hex, True),
        (str(uuid.uuid4()), True),
        ("A_b-9" * 25 + "xyz", True),  # 128 characters
        ("abcdefg", False),  # 7 characters
        ("a" * 129, False),
        ("has space here", False),
        ("reschedule:anything", False),  # the server's own namespace
        ("café-key-123", False),
    ],
)
def test_client_key_rules(key: str, valid: bool) -> None:
    assert is_client_key(key) is valid


def test_reschedule_keys_fit_the_column_but_never_look_like_client_keys() -> None:
    key = reschedule_key(uuid.uuid4())
    assert 8 <= len(key) <= 128
    assert not is_client_key(key)
