# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The patient read API: search, filters, the profile and clinic scoping."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import ClinicRole, ConversationState, PatientStatus
from app.models import Patient
from tests.conftest import ClientFactory
from tests.support.booking import FUTURE_MONDAY, BookingClinic, build_booking_clinic, headers_for
from tests.support.records import add_conversation, add_patient, add_scenario, add_snapshot

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings, session_factory: SessionFactory
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


@pytest.fixture
async def clinic(session_factory: SessionFactory) -> BookingClinic:
    """Comes with one patient, Robin Example (prospective)."""
    return await build_booking_clinic(session_factory)


def viewer(settings: Settings, clinic: BookingClinic) -> dict[str, str]:
    return headers_for(settings, clinic.clinic_id, ClinicRole.VIEWER)


async def _names(client: httpx.AsyncClient, headers: dict[str, str], query: str) -> list[str]:
    response = await client.get(f"/api/v1/patients{query}", headers=headers)
    assert response.status_code == 200, response.text
    return [f"{p['first_name']} {p['last_name']}" for p in response.json()]


async def test_search_matches_name_full_name_and_email_case_insensitively(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    cid = clinic.clinic_id
    await add_patient(session_factory, cid, "Ava", "Lindqvist", email="ava.l@example.com")
    await add_patient(session_factory, cid, "Bo", "Avalon", phone="+1-555-0142")
    await add_patient(session_factory, cid, "Cy", "Okafor", email="cy_100%@example.org")
    headers = viewer(database_settings, clinic)

    # Ordered by last name, then first name.
    assert await _names(client, headers, "") == [
        "Bo Avalon",
        "Robin Example",
        "Ava Lindqvist",
        "Cy Okafor",
    ]
    assert await _names(client, headers, "?q=ava") == ["Bo Avalon", "Ava Lindqvist"]
    assert await _names(client, headers, "?q=AVA%20LIND") == ["Ava Lindqvist"]
    assert await _names(client, headers, "?q=example.org") == ["Cy Okafor"]
    assert await _names(client, headers, "?q=%20%20") == await _names(client, headers, "")
    # LIKE wildcards are literal characters, not patterns.
    assert await _names(client, headers, "?q=_100%25") == ["Cy Okafor"]
    assert await _names(client, headers, "?q=%25") == ["Cy Okafor"]
    assert await _names(client, headers, "?q=nobody") == []
    # Phone numbers are not a search key.
    assert await _names(client, headers, "?q=555-0142") == []


async def test_status_filter_and_pagination(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    cid = clinic.clinic_id
    for index in range(4):
        await add_patient(
            session_factory,
            cid,
            "Reg",
            f"Patient{index}",
            email=f"reg{index}@example.net",
            status=PatientStatus.REGISTERED,
        )
    await add_patient(
        session_factory,
        cid,
        "Old",
        "Archived",
        email="old@example.com",
        status=PatientStatus.ARCHIVED,
    )
    headers = viewer(database_settings, clinic)

    assert await _names(client, headers, "?status=archived") == ["Old Archived"]
    assert await _names(client, headers, "?status=prospective") == ["Robin Example"]
    registered = await _names(client, headers, "?status=registered")
    assert registered == [f"Reg Patient{i}" for i in range(4)]
    first = await _names(client, headers, "?status=registered&limit=3")
    second = await _names(client, headers, "?status=registered&limit=3&offset=3")
    assert first + second == registered
    assert await _names(client, headers, "?status=registered&q=patient2") == ["Reg Patient2"]

    for query in ("?limit=0", "?limit=101", "?offset=-1", "?status=deleted", f"?q={'x' * 255}"):
        response = await client.get(f"/api/v1/patients{query}", headers=headers)
        assert (response.status_code, response.json()["error"]["code"]) == (
            400,
            "VALIDATION_ERROR",
        ), query


async def test_profile_links_conversations_snapshots_and_appointments(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    cid, patient_id = clinic.clinic_id, clinic.patient_id
    scenario_id = await add_scenario(session_factory, cid)
    older = await add_conversation(
        session_factory,
        cid,
        scenario_id,
        state=ConversationState.COMPLETED,
        created_at=T0,
        started_at=T0,
        ended_at=T0 + timedelta(minutes=4),
        patient_id=patient_id,
    )
    newer = await add_conversation(
        session_factory,
        cid,
        scenario_id,
        state=ConversationState.COMPLETED,
        created_at=T0 + timedelta(days=1),
        started_at=T0 + timedelta(days=1),
        ended_at=T0 + timedelta(days=1, minutes=3),
        patient_id=patient_id,
    )
    await add_snapshot(session_factory, cid, older, T0 + timedelta(minutes=4))
    await add_snapshot(
        session_factory,
        cid,
        newer,
        T0 + timedelta(days=1, minutes=3),
        visit_reason="Chipped tooth",
        requested_service="checkup",
        preferred_time="14:30:00",
    )
    # Not linked to this patient: never listed on the profile.
    other_patient = await add_patient(session_factory, cid, "Ava", "Other", email="o@example.com")
    await add_conversation(
        session_factory,
        cid,
        scenario_id,
        state=ConversationState.CREATED,
        created_at=T0,
        patient_id=other_patient,
    )
    await add_conversation(
        session_factory, cid, scenario_id, state=ConversationState.CREATED, created_at=T0
    )

    staff = headers_for(database_settings, cid, ClinicRole.STAFF)
    booked = await client.post(
        "/api/v1/appointments",
        json={
            "patient_id": str(patient_id),
            "appointment_type_id": str(clinic.checkup_id),
            "dentist_id": str(clinic.dentist_a),
            "starts_at": clinic.at(FUTURE_MONDAY, 9).isoformat(),
        },
        headers={**staff, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert booked.status_code == 201, booked.text
    moved = await client.post(
        f"/api/v1/appointments/{booked.json()['id']}/reschedule",
        json={"starts_at": clinic.at(FUTURE_MONDAY, 11).isoformat()},
        headers=staff,
    )
    assert moved.status_code == 201, moved.text

    response = await client.get(
        f"/api/v1/patients/{patient_id}", headers=viewer(database_settings, clinic)
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["patient"]["id"] == str(patient_id)
    assert body["patient"]["first_name"] == "Robin"
    assert body["patient"]["email"].endswith("@example.com")
    assert [c["id"] for c in body["conversations"]] == [str(newer), str(older)]
    assert body["conversations"][0]["state"] == "COMPLETED"
    assert body["conversations"][0]["snapshot_confirmed_at"] == "2026-10-02T09:03:00Z"
    assert body["conversations"][1]["ended_at"] == "2026-10-01T09:04:00Z"
    assert body["latest_snapshot"] == {
        "conversation_id": str(newer),
        "confirmed_at": "2026-10-02T09:03:00Z",
        "patient_type": "new",
        "preferred_contact_channel": "email",
        "visit_reason": "Chipped tooth",
        "requested_service": "checkup",
        "preferred_date": "2030-01-07",
        "preferred_time": "14:30:00",
    }
    # Every status is listed, latest start first, with clinic-local times.
    appointments = body["appointments"]
    assert [(a["status"], a["starts_at_local"]) for a in appointments] == [
        ("confirmed", "2030-01-07T11:00:00+00:00"),
        ("rescheduled", "2030-01-07T09:00:00+00:00"),
    ]
    assert appointments[0]["rescheduled_from_id"] == appointments[1]["id"]
    assert appointments[0]["timezone"] == "Europe/London"


async def test_a_patient_without_history_has_empty_lists(
    client: httpx.AsyncClient, clinic: BookingClinic, database_settings: Settings
) -> None:
    response = await client.get(
        f"/api/v1/patients/{clinic.patient_id}", headers=viewer(database_settings, clinic)
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["conversations"], body["appointments"], body["latest_snapshot"]) == ([], [], None)


async def test_other_clinics_patients_are_invisible(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    other = await build_booking_clinic(session_factory)
    empty = await build_booking_clinic(session_factory)
    mine = viewer(database_settings, clinic)
    theirs = headers_for(database_settings, other.clinic_id, ClinicRole.ADMIN)

    listed = await client.get("/api/v1/patients", headers=theirs)
    assert [p["id"] for p in listed.json()] == [str(other.patient_id)]
    assert str(clinic.patient_id) not in listed.text

    for patient_id in (clinic.patient_id, uuid.uuid4()):
        response = await client.get(f"/api/v1/patients/{patient_id}", headers=theirs)
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "NOT_FOUND",
            "message": "Patient not found.",
            "request_id": response.headers["x-request-id"],
        }
    # A clinic id in the query string is ignored: the token decides.
    smuggled = await client.get(f"/api/v1/patients?clinic_id={other.clinic_id}", headers=mine)
    assert [p["id"] for p in smuggled.json()] == [str(clinic.patient_id)]

    # A clinic with no patients at all.
    async with session_factory.begin() as session:
        await session.execute(delete(Patient).where(Patient.clinic_id == empty.clinic_id))
    nobody = headers_for(database_settings, empty.clinic_id, ClinicRole.VIEWER)
    assert (await client.get("/api/v1/patients", headers=nobody)).json() == []


async def test_patients_require_a_token(client: httpx.AsyncClient, clinic: BookingClinic) -> None:
    for path in ("/api/v1/patients", f"/api/v1/patients/{clinic.patient_id}"):
        response = await client.get(path)
        assert (response.status_code, response.json()["error"]["code"]) == (401, "AUTH_REQUIRED")
