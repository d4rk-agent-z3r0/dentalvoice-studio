# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Availability against PostgreSQL: published slots minus active appointments, in local time."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import AppointmentStatus, ClinicRole, SlotStatus
from app.domain.errors import NotFoundError
from app.models import Appointment, AppointmentType, Dentist
from app.services.booking.availability import AvailabilityService
from tests.conftest import ClientFactory
from tests.support.booking import (
    FUTURE_MONDAY,
    BookingClinic,
    build_booking_clinic,
    headers_for,
    set_slot_status,
)

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def clinic(session_factory: SessionFactory) -> BookingClinic:
    return await build_booking_clinic(session_factory)


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


def service_at(session_factory: SessionFactory, now: datetime) -> AvailabilityService:
    return AvailabilityService(session_factory, clock=lambda: now)


async def insert_appointment(
    session_factory: SessionFactory,
    clinic: BookingClinic,
    dentist_id: uuid.UUID,
    starts_at: datetime,
    minutes: int,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
) -> None:
    async with session_factory.begin() as session:
        session.add(
            Appointment(
                clinic_id=clinic.clinic_id,
                patient_id=clinic.patient_id,
                dentist_id=dentist_id,
                appointment_type_id=clinic.checkup_id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=minutes),
                status=status,
                idempotency_key=f"seeded-{uuid.uuid4().hex}",
                request_hash="0" * 64,
            )
        )


def local_starts(body: dict[str, object], dentist_id: uuid.UUID) -> list[str]:
    slots = body["slots"]
    assert isinstance(slots, list)
    return [s["starts_at_local"][11:16] for s in slots if s["dentist_id"] == str(dentist_id)]


async def test_api_lists_runs_long_enough_for_the_type(
    client: httpx.AsyncClient, clinic: BookingClinic, database_settings: Settings
) -> None:
    response = await client.get(
        "/api/v1/availability",
        params={"appointment_type_id": str(clinic.cleaning_id), "date": "2030-01-07"},
        headers=headers_for(database_settings, clinic.clinic_id, ClinicRole.VIEWER),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["duration_minutes"] == 45
    assert body["timezone"] == "Europe/London"
    assert (body["first_day"], body["days"]) == ("2030-01-07", 1)
    # 09:00-12:00 fits a 45-minute visit at every quarter hour up to 11:15; 10:00-11:00 twice.
    assert local_starts(body, clinic.dentist_a) == [
        "09:00", "09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15",
    ]  # fmt: skip
    assert local_starts(body, clinic.dentist_b) == ["10:00", "10:15"]
    first = body["slots"][0]
    assert first == {
        "dentist_id": str(clinic.dentist_a),
        "dentist_name": "Dr. Ada Example",
        "starts_at": "2030-01-07T09:00:00Z",
        "ends_at": "2030-01-07T09:45:00Z",
        "starts_at_local": "2030-01-07T09:00:00+00:00",
        "ends_at_local": "2030-01-07T09:45:00+00:00",
    }
    starts = [s["starts_at"] for s in body["slots"]]
    assert starts == sorted(starts)


async def test_active_appointments_hide_times_but_cancelled_ones_do_not(
    session_factory: SessionFactory, clinic: BookingClinic
) -> None:
    day = FUTURE_MONDAY
    await insert_appointment(session_factory, clinic, clinic.dentist_a, clinic.at(day, 10), 30)
    await insert_appointment(
        session_factory,
        clinic,
        clinic.dentist_a,
        clinic.at(day, 11),
        30,
        AppointmentStatus.REQUESTED,
    )
    await insert_appointment(
        session_factory,
        clinic,
        clinic.dentist_b,
        clinic.at(day, 10),
        30,
        AppointmentStatus.CANCELLED,
    )

    result = await AvailabilityService(session_factory).find(
        clinic.clinic_id, clinic.checkup_id, day
    )

    a = [s.starts_at_local[11:16] for s in result.slots if s.dentist_id == clinic.dentist_a]
    b = [s.starts_at_local[11:16] for s in result.slots if s.dentist_id == clinic.dentist_b]
    assert a == ["09:00", "09:15", "09:30", "10:30", "11:30"]
    assert b == ["10:00", "10:15", "10:30"]


async def test_blocked_slots_and_inactive_dentists_are_not_offered(
    session_factory: SessionFactory, clinic: BookingClinic
) -> None:
    day = FUTURE_MONDAY
    await set_slot_status(
        session_factory, clinic, clinic.dentist_a, clinic.at(day, 9, 30), SlotStatus.BLOCKED
    )
    async with session_factory.begin() as session:
        await session.execute(
            update(Dentist).where(Dentist.id == clinic.dentist_b).values(is_active=False)
        )

    result = await AvailabilityService(session_factory).find(
        clinic.clinic_id, clinic.checkup_id, day
    )

    assert {s.dentist_id for s in result.slots} == {clinic.dentist_a}
    assert [s.starts_at_local[11:16] for s in result.slots] == [
        "09:00", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
    ]  # fmt: skip


async def test_only_future_times_are_offered(
    session_factory: SessionFactory, clinic: BookingClinic
) -> None:
    now = clinic.at(FUTURE_MONDAY, 10, 40)
    result = await service_at(session_factory, now).find(
        clinic.clinic_id, clinic.checkup_id, FUTURE_MONDAY
    )
    assert [s.starts_at_local[11:16] for s in result.slots] == ["10:45", "11:00", "11:15", "11:30"]
    assert all(s.starts_at > now for s in result.slots)


async def test_unknown_inactive_and_foreign_appointment_types_are_not_found(
    session_factory: SessionFactory, clinic: BookingClinic
) -> None:
    other = await build_booking_clinic(session_factory)
    service = AvailabilityService(session_factory)
    async with session_factory.begin() as session:
        await session.execute(
            update(AppointmentType)
            .where(AppointmentType.id == clinic.cleaning_id)
            .values(is_active=False)
        )

    for type_id in (uuid.uuid4(), other.checkup_id, clinic.cleaning_id):
        with pytest.raises(NotFoundError) as caught:
            await service.find(clinic.clinic_id, type_id, FUTURE_MONDAY)
        assert caught.value.message == "Appointment type not found."


async def test_api_another_clinics_type_is_404_and_bad_queries_are_400(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    clinic: BookingClinic,
    database_settings: Settings,
) -> None:
    other = await build_booking_clinic(session_factory)
    headers = headers_for(database_settings, clinic.clinic_id, ClinicRole.STAFF)

    foreign = await client.get(
        "/api/v1/availability",
        params={"appointment_type_id": str(other.checkup_id), "date": "2030-01-07"},
        headers=headers,
    )
    assert (foreign.status_code, foreign.json()["error"]["code"]) == (404, "NOT_FOUND")

    for params in (
        {"appointment_type_id": str(clinic.checkup_id)},
        {"appointment_type_id": str(clinic.checkup_id), "date": "2030-01-07", "days": "15"},
        {"appointment_type_id": "nope", "date": "2030-01-07"},
    ):
        bad = await client.get("/api/v1/availability", params=params, headers=headers)
        assert (bad.status_code, bad.json()["error"]["code"]) == (400, "VALIDATION_ERROR")

    unauthenticated = await client.get(
        "/api/v1/availability",
        params={"appointment_type_id": str(clinic.checkup_id), "date": "2030-01-07"},
    )
    assert unauthenticated.status_code == 401


@pytest.mark.parametrize(
    ("timezone", "first_day", "before_utc", "after_utc"),
    [
        # Europe/London springs forward on Sunday 2026-03-29 and falls back on 2026-10-25.
        ("Europe/London", date(2026, 3, 28), "09:00", "08:00"),
        ("Europe/London", date(2026, 10, 24), "08:00", "09:00"),
        # America/New_York falls back on Sunday 2026-11-01.
        ("America/New_York", date(2026, 10, 31), "13:00", "14:00"),
    ],
)
async def test_local_opening_hours_hold_across_dst(
    session_factory: SessionFactory,
    timezone: str,
    first_day: date,
    before_utc: str,
    after_utc: str,
) -> None:
    clinic = await build_booking_clinic(
        session_factory, timezone=timezone, first_day=first_day, days=2
    )
    now = datetime.combine(first_day - timedelta(days=7), datetime.min.time(), tzinfo=UTC)

    result = await service_at(session_factory, now).find(
        clinic.clinic_id, clinic.checkup_id, first_day, days=2
    )

    mine = [s for s in result.slots if s.dentist_id == clinic.dentist_a]
    assert len(mine) == 2 * 11  # 09:00 … 11:30 on each day
    by_day: dict[str, list[str]] = {}
    for slot in mine:
        by_day.setdefault(slot.starts_at_local[:10], []).append(slot.starts_at_local[11:16])
    assert list(by_day) == [first_day.isoformat(), (first_day + timedelta(days=1)).isoformat()]
    assert all(times[0] == "09:00" and times[-1] == "11:30" for times in by_day.values())
    assert mine[0].starts_at.strftime("%H:%M") == before_utc
    assert mine[11].starts_at.strftime("%H:%M") == after_utc
    for slot in mine:
        assert datetime.fromisoformat(slot.starts_at_local) == slot.starts_at
