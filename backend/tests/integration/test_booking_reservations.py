# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Reservations against PostgreSQL: book, replay, cancel, reschedule, isolation and validation."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import AppointmentStatus, ClinicRole, SlotStatus
from app.domain.errors import SlotUnavailableError
from app.models import Appointment, Dentist, DentistSchedule
from app.schemas.booking import AppointmentCreate
from app.services.booking.reservations import ReservationService
from app.services.calendar import publish_slots
from tests.conftest import ClientFactory
from tests.support.booking import (
    FUTURE_MONDAY,
    BookingClinic,
    build_booking_clinic,
    headers_for,
    set_slot_status,
)
from tests.support.factories import build_clinic_graph

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
DAY = FUTURE_MONDAY


@pytest.fixture
async def clinic(session_factory: SessionFactory) -> BookingClinic:
    return await build_booking_clinic(session_factory)


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


@pytest.fixture
def staff(database_settings: Settings, clinic: BookingClinic) -> dict[str, str]:
    return headers_for(database_settings, clinic.clinic_id, ClinicRole.STAFF)


def new_key() -> str:
    return uuid.uuid4().hex


def payload(clinic: BookingClinic, starts_at: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "patient_id": str(clinic.patient_id),
        "appointment_type_id": str(clinic.checkup_id),
        "dentist_id": str(clinic.dentist_a),
        "starts_at": starts_at.isoformat(),
        **overrides,
    }


async def book(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    body: dict[str, Any],
    key: str | None = None,
) -> httpx.Response:
    return await client.post(
        "/api/v1/appointments", json=body, headers={**headers, "Idempotency-Key": key or new_key()}
    )


def error_of(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def appointments_in(
    session_factory: SessionFactory, clinic_id: uuid.UUID
) -> list[Appointment]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(Appointment)
            .where(Appointment.clinic_id == clinic_id)
            .order_by(Appointment.created_at, Appointment.id)
        )
        return list(rows.all())


async def test_booking_is_confirmed_persisted_and_leaves_availability(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    response = await book(client, staff, payload(clinic, clinic.at(DAY, 9)))

    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    body = response.json()
    assert body["status"] == "confirmed"
    assert (body["starts_at"], body["ends_at"]) == ("2030-01-07T09:00:00Z", "2030-01-07T09:30:00Z")
    assert body["starts_at_local"] == "2030-01-07T09:00:00+00:00"
    assert body["timezone"] == "Europe/London"
    assert body["rescheduled_from_id"] is None
    rows = await appointments_in(session_factory, clinic.clinic_id)
    assert [(str(r.id), r.status) for r in rows] == [(body["id"], AppointmentStatus.CONFIRMED)]

    availability = await client.get(
        "/api/v1/availability",
        params={"appointment_type_id": str(clinic.checkup_id), "date": DAY.isoformat()},
        headers=staff,
    )
    offered = {(s["dentist_id"], s["starts_at"]) for s in availability.json()["slots"]}
    for minute in (0, 15):  # 09:00 and 09:15 overlap the booking; 09:30 does not
        assert (str(clinic.dentist_a), f"2030-01-07T09:{minute:02d}:00Z") not in offered
    assert (str(clinic.dentist_a), "2030-01-07T09:30:00Z") in offered


async def test_replay_with_same_key_and_body_returns_the_original(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    key = new_key()
    first = await book(client, staff, payload(clinic, clinic.at(DAY, 9)), key)
    # Same instant written with another offset is the same request.
    same_instant = {**payload(clinic, clinic.at(DAY, 9)), "starts_at": "2030-01-07T10:00:00+01:00"}
    second = await book(client, staff, same_instant, key)

    assert first.status_code == second.status_code == 201
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json() == first.json()
    assert len(await appointments_in(session_factory, clinic.clinic_id)) == 1


async def test_replay_with_a_different_body_is_a_conflict(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    key = new_key()
    await book(client, staff, payload(clinic, clinic.at(DAY, 9)), key)

    for changed in (
        payload(clinic, clinic.at(DAY, 10)),
        payload(clinic, clinic.at(DAY, 9), dentist_id=str(clinic.dentist_b)),
        payload(clinic, clinic.at(DAY, 9), appointment_type_id=str(clinic.cleaning_id)),
    ):
        response = await book(client, staff, changed, key)
        assert error_of(response) == (409, "IDEMPOTENCY_CONFLICT")
    rows = await appointments_in(session_factory, clinic.clinic_id)
    assert [(r.starts_at, r.dentist_id) for r in rows] == [(clinic.at(DAY, 9), clinic.dentist_a)]


async def test_a_replay_returns_the_appointment_as_it_is_now(
    client: httpx.AsyncClient, clinic: BookingClinic, staff: dict[str, str]
) -> None:
    key = new_key()
    body = payload(clinic, clinic.at(DAY, 9))
    created = (await book(client, staff, body, key)).json()
    await client.post(f"/api/v1/appointments/{created['id']}/cancel", headers=staff)

    replay = await book(client, staff, body, key)

    assert (replay.status_code, replay.json()["id"]) == (201, created["id"])
    assert replay.json()["status"] == "cancelled"  # never silently re-booked


async def test_idempotency_keys_are_scoped_to_the_clinic(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    other = await build_booking_clinic(session_factory)
    other_staff = headers_for(database_settings, other.clinic_id, ClinicRole.STAFF)
    key = new_key()

    mine = await book(client, staff, payload(clinic, clinic.at(DAY, 9)), key)
    theirs = await book(client, other_staff, payload(other, other.at(DAY, 9)), key)

    assert mine.status_code == theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]
    assert "Idempotent-Replayed" not in theirs.headers


async def test_overlapping_booking_is_taken_but_adjacent_and_other_dentist_are_fine(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    assert (await book(client, staff, payload(clinic, clinic.at(DAY, 10)))).status_code == 201

    for start in (clinic.at(DAY, 10), clinic.at(DAY, 9, 45), clinic.at(DAY, 10, 15)):
        taken = await book(client, staff, payload(clinic, start))
        assert error_of(taken) == (409, "BOOKING_SLOT_TAKEN")
        assert taken.json()["error"]["message"] == "That time is no longer available."

    adjacent = await book(client, staff, payload(clinic, clinic.at(DAY, 10, 30)))
    other_dentist = await book(
        client, staff, payload(clinic, clinic.at(DAY, 10), dentist_id=str(clinic.dentist_b))
    )
    assert adjacent.status_code == other_dentist.status_code == 201
    assert len(await appointments_in(session_factory, clinic.clinic_id)) == 3


async def test_cancel_frees_the_time_for_a_new_booking(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    created = (await book(client, staff, payload(clinic, clinic.at(DAY, 11)))).json()
    url = f"/api/v1/appointments/{created['id']}/cancel"

    cancelled = await client.post(url, headers=staff)
    again = await client.post(url, headers=staff)
    rebooked = await book(client, staff, payload(clinic, clinic.at(DAY, 11)))

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["id"] == created["id"]
    assert error_of(again) == (409, "APPOINTMENT_NOT_ACTIVE")
    assert rebooked.status_code == 201
    rows = await appointments_in(session_factory, clinic.clinic_id)
    assert [r.status for r in rows] == [AppointmentStatus.CANCELLED, AppointmentStatus.CONFIRMED]


async def test_reschedule_replaces_the_appointment_atomically(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    created = (await book(client, staff, payload(clinic, clinic.at(DAY, 9)))).json()

    # 15 minutes later overlaps the original: allowed, because the original is released first.
    moved = await client.post(
        f"/api/v1/appointments/{created['id']}/reschedule",
        json={"starts_at": clinic.at(DAY, 9, 15).isoformat()},
        headers=staff,
    )

    assert moved.status_code == 201
    new = moved.json()
    assert new["id"] != created["id"]
    assert new["rescheduled_from_id"] == created["id"]
    assert (new["status"], new["starts_at"], new["ends_at"]) == (
        "confirmed", "2030-01-07T09:15:00Z", "2030-01-07T09:45:00Z",
    )  # fmt: skip
    assert (new["patient_id"], new["dentist_id"], new["appointment_type_id"]) == (
        created["patient_id"], created["dentist_id"], created["appointment_type_id"],
    )  # fmt: skip
    rows = {str(r.id): r for r in await appointments_in(session_factory, clinic.clinic_id)}
    assert rows[created["id"]].status is AppointmentStatus.RESCHEDULED
    assert rows[new["id"]].idempotency_key == f"reschedule:{created['id']}"

    second = await client.post(
        f"/api/v1/appointments/{created['id']}/reschedule",
        json={"starts_at": clinic.at(DAY, 11).isoformat()},
        headers=staff,
    )
    assert error_of(second) == (409, "APPOINTMENT_NOT_ACTIVE")


@pytest.mark.parametrize("obstacle", ["taken", "blocked", "unpublished", "past"])
async def test_failed_reschedule_leaves_the_original_untouched(
    obstacle: str,
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    created = (await book(client, staff, payload(clinic, clinic.at(DAY, 9)))).json()
    target = clinic.at(DAY, 10)
    expected = (409, "SLOT_UNAVAILABLE")
    if obstacle == "taken":
        assert (await book(client, staff, payload(clinic, target))).status_code == 201
        expected = (409, "BOOKING_SLOT_TAKEN")
    elif obstacle == "blocked":
        await set_slot_status(session_factory, clinic, clinic.dentist_a, target, SlotStatus.BLOCKED)
    elif obstacle == "unpublished":
        target = clinic.at(DAY, 14)
    else:
        target = datetime(2020, 1, 6, 10, 0, tzinfo=UTC)
    before = await appointments_in(session_factory, clinic.clinic_id)

    response = await client.post(
        f"/api/v1/appointments/{created['id']}/reschedule",
        json={"starts_at": target.isoformat()},
        headers=staff,
    )

    assert error_of(response) == expected
    after = await appointments_in(session_factory, clinic.clinic_id)
    assert [(r.id, r.status, r.starts_at, r.updated_at) for r in after] == [
        (r.id, r.status, r.starts_at, r.updated_at) for r in before
    ]
    original = next(r for r in after if str(r.id) == created["id"])
    assert original.status is AppointmentStatus.CONFIRMED


@pytest.mark.parametrize(
    ("start", "message"),
    [
        ((DAY, 9, 5), "That time is not open for booking."),  # not on a slot boundary
        ((DAY, 11, 45), "That time is not open for booking."),  # runs past closing time
        ((DAY, 13, 0), "That time is not open for booking."),  # nothing published
        (
            (DAY + timedelta(days=1), 9, 0),
            "That time is not open for booking.",
        ),  # day not published
    ],
)
async def test_unpublished_times_are_unavailable(
    start: tuple[date, int, int],
    message: str,
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
) -> None:
    response = await book(client, staff, payload(clinic, clinic.at(*start)))
    assert error_of(response) == (409, "SLOT_UNAVAILABLE")
    assert response.json()["error"]["message"] == message


async def test_blocked_slots_and_inactive_dentists_are_unavailable(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    await set_slot_status(
        session_factory, clinic, clinic.dentist_a, clinic.at(DAY, 9, 15), SlotStatus.BLOCKED
    )
    blocked = await book(client, staff, payload(clinic, clinic.at(DAY, 9)))
    assert error_of(blocked) == (409, "SLOT_UNAVAILABLE")

    async with session_factory.begin() as session:
        await session.execute(
            update(Dentist).where(Dentist.id == clinic.dentist_b).values(is_active=False)
        )
    inactive = await book(
        client, staff, payload(clinic, clinic.at(DAY, 10), dentist_id=str(clinic.dentist_b))
    )
    assert error_of(inactive) == (409, "SLOT_UNAVAILABLE")
    assert inactive.json()["error"]["message"] == "That dentist is not taking bookings."
    assert await appointments_in(session_factory, clinic.clinic_id) == []


async def test_past_times_are_rejected(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    response = await book(client, staff, payload(clinic, datetime(2020, 1, 6, 9, tzinfo=UTC)))
    assert error_of(response) == (409, "SLOT_UNAVAILABLE")
    assert response.json()["error"]["message"] == "That time is in the past."

    # A published slot that "now" has reached is in the past too, even by a second.
    start = clinic.at(DAY, 9)
    service = ReservationService(session_factory, clock=lambda: start)
    request = AppointmentCreate.model_validate(payload(clinic, start))
    with pytest.raises(SlotUnavailableError, match="past"):
        await service.reserve(clinic.clinic_id, request, new_key())
    later = ReservationService(session_factory, clock=lambda: start - timedelta(seconds=1))
    assert (
        await later.reserve(clinic.clinic_id, request, new_key())
    ).appointment.starts_at == start


async def test_another_clinics_resources_are_not_found(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    other = await build_booking_clinic(session_factory)
    graph = await build_clinic_graph(session_factory, uuid.uuid4().hex[:8])
    start = clinic.at(DAY, 9)

    for field, value, resource in [
        ("patient_id", other.patient_id, "Patient"),
        ("appointment_type_id", other.checkup_id, "Appointment type"),
        ("dentist_id", other.dentist_a, "Dentist"),
        ("conversation_id", graph.conversation_id, "Conversation"),
        ("patient_id", uuid.uuid4(), "Patient"),
    ]:
        response = await book(client, staff, payload(clinic, start, **{field: str(value)}))
        assert error_of(response) == (404, "NOT_FOUND"), field
        assert response.json()["error"]["message"] == f"{resource} not found."

    other_staff = headers_for(database_settings, other.clinic_id, ClinicRole.ADMIN)
    theirs = (await book(client, other_staff, payload(other, other.at(DAY, 9)))).json()
    for path, body in [("cancel", None), ("reschedule", {"starts_at": start.isoformat()})]:
        response = await client.post(
            f"/api/v1/appointments/{theirs['id']}/{path}", json=body, headers=staff
        )
        assert error_of(response) == (404, "NOT_FOUND"), path
        assert response.json()["error"]["message"] == "Appointment not found."
    listed = await client.get("/api/v1/appointments", headers=staff)
    assert listed.json() == []
    untouched = await appointments_in(session_factory, other.clinic_id)
    assert [r.status for r in untouched] == [AppointmentStatus.CONFIRMED]


async def test_a_conversation_of_the_same_clinic_is_linked(
    client: httpx.AsyncClient, session_factory: SessionFactory, database_settings: Settings
) -> None:
    graph = await build_clinic_graph(session_factory, uuid.uuid4().hex[:8])
    async with session_factory.begin() as session:
        session.add(
            DentistSchedule(
                clinic_id=graph.clinic_id,
                dentist_id=graph.dentist_id,
                weekday=DAY.weekday(),
                start_local=time(9, 0),
                end_local=time(10, 0),
            )
        )
        await session.flush()
        await publish_slots(session, graph.clinic_id, "Europe/London", DAY, 1)
    headers = headers_for(database_settings, graph.clinic_id, ClinicRole.ADMIN)
    body = {
        "patient_id": str(graph.patient_id),
        "appointment_type_id": str(graph.appointment_type_id),
        "dentist_id": str(graph.dentist_id),
        "conversation_id": str(graph.conversation_id),
        "starts_at": "2030-01-07T09:00:00Z",
    }

    response = await book(client, headers, body)

    assert response.status_code == 201
    assert response.json()["conversation_id"] == str(graph.conversation_id)


async def test_viewers_can_read_but_not_write(
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    database_settings: Settings,
    session_factory: SessionFactory,
) -> None:
    viewer = headers_for(database_settings, clinic.clinic_id, ClinicRole.VIEWER)
    created = (await book(client, staff, payload(clinic, clinic.at(DAY, 9)))).json()

    attempts = [
        await book(client, viewer, payload(clinic, clinic.at(DAY, 10))),
        await client.post(f"/api/v1/appointments/{created['id']}/cancel", headers=viewer),
        await client.post(
            f"/api/v1/appointments/{created['id']}/reschedule",
            json={"starts_at": clinic.at(DAY, 11).isoformat()},
            headers=viewer,
        ),
    ]
    assert [error_of(r) for r in attempts] == [(403, "FORBIDDEN")] * 3
    listed = await client.get("/api/v1/appointments", headers=viewer)
    assert [a["id"] for a in listed.json()] == [created["id"]]
    rows = await appointments_in(session_factory, clinic.clinic_id)
    assert [r.status for r in rows] == [AppointmentStatus.CONFIRMED]


@pytest.mark.parametrize(
    ("key", "body_change"),
    [
        (None, {}),  # header missing
        ("short", {}),
        ("x" * 129, {}),
        ("reschedule:abcdef", {}),  # the server's own namespace
        ("valid-key-123", {"starts_at": "2030-01-07T09:00:00"}),  # naive time
        ("valid-key-456", {"clinic_id": str(uuid.uuid4())}),  # clinic comes from the token
    ],
)
async def test_invalid_requests_are_400(
    key: str | None,
    body_change: dict[str, Any],
    client: httpx.AsyncClient,
    clinic: BookingClinic,
    staff: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    headers = dict(staff)
    if key is not None:
        headers["Idempotency-Key"] = key
    body = {**payload(clinic, clinic.at(DAY, 9)), **body_change}
    response = await client.post("/api/v1/appointments", json=body, headers=headers)
    assert error_of(response) == (400, "VALIDATION_ERROR")
    assert await appointments_in(session_factory, clinic.clinic_id) == []


async def test_list_filters_by_local_day_and_status(
    client: httpx.AsyncClient, session_factory: SessionFactory, database_settings: Settings
) -> None:
    clinic = await build_booking_clinic(session_factory, first_day=DAY, days=3)
    staff = headers_for(database_settings, clinic.clinic_id, ClinicRole.STAFF)
    ids = []
    for offset in range(3):
        day = DAY + timedelta(days=offset)
        ids.append((await book(client, staff, payload(clinic, clinic.at(day, 9)))).json()["id"])
    await client.post(f"/api/v1/appointments/{ids[1]}/cancel", headers=staff)

    async def listed(**params: str) -> list[str]:
        response = await client.get("/api/v1/appointments", params=params, headers=staff)
        assert response.status_code == 200
        return [a["id"] for a in response.json()]

    assert await listed() == ids
    assert await listed(**{"from": "2030-01-08"}) == ids[1:]
    assert await listed(to="2030-01-08") == ids[:2]
    assert await listed(**{"from": "2030-01-08", "to": "2030-01-08"}) == [ids[1]]
    assert await listed(status="cancelled") == [ids[1]]
    assert await listed(status="confirmed", limit="1") == [ids[0]]
    bad = await client.get(
        "/api/v1/appointments", params={"from": "2030-01-09", "to": "2030-01-08"}, headers=staff
    )
    assert error_of(bad) == (400, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    ("timezone", "first_day", "local_hour", "expected_utc", "expected_local"),
    [
        (
            "Europe/London",
            date(2026, 3, 29),
            9,
            "2026-03-29T08:00:00Z",
            "2026-03-29T09:00:00+01:00",
        ),
        (
            "Europe/London",
            date(2026, 10, 25),
            9,
            "2026-10-25T09:00:00Z",
            "2026-10-25T09:00:00+00:00",
        ),
        (
            "America/New_York",
            date(2026, 11, 1),
            9,
            "2026-11-01T14:00:00Z",
            "2026-11-01T09:00:00-05:00",
        ),
    ],
)
async def test_booking_on_a_dst_change_day(
    timezone: str,
    first_day: date,
    local_hour: int,
    expected_utc: str,
    expected_local: str,
    session_factory: SessionFactory,
) -> None:
    clinic = await build_booking_clinic(session_factory, timezone=timezone, first_day=first_day)
    now = datetime(first_day.year, first_day.month, 1, tzinfo=UTC)
    service = ReservationService(session_factory, clock=lambda: now)
    start = clinic.at(first_day, local_hour)

    booked = await service.reserve(
        clinic.clinic_id, AppointmentCreate.model_validate(payload(clinic, start)), new_key()
    )

    read = booked.appointment.model_dump(mode="json")
    assert (read["starts_at"], read["starts_at_local"]) == (expected_utc, expected_local)
    assert booked.appointment.ends_at - booked.appointment.starts_at == timedelta(minutes=30)
    listed = await service.list(clinic.clinic_id, first_day=first_day, last_day=first_day)
    assert [a.id for a in listed] == [booked.appointment.id]
    count = 0
    async with session_factory() as session:
        count = (
            await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.clinic_id == clinic.clinic_id)
            )
            or 0
        )
    assert count == 1
