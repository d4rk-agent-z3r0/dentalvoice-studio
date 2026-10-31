# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Concurrent booking against PostgreSQL: the database, not the application, decides the race.

The barrier tests hold every transaction after it has read the calendar and before it inserts,
so all of them are open at once, each on its own PostgreSQL backend, and all have seen the time
as free. Whatever happens next can only be decided by the database constraints.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus, ClinicRole
from app.domain.errors import (
    AppointmentNotActiveError,
    BookingSlotTakenError,
    IdempotencyConflictError,
)
from app.models import Appointment
from app.schemas.booking import AppointmentCreate
from app.services.booking.reservations import Reservation, ReservationService
from tests.conftest import ClientFactory
from tests.support.booking import FUTURE_MONDAY, BookingClinic, build_booking_clinic, headers_for

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
DAY = FUTURE_MONDAY
N = 20
BARRIER_TIMEOUT_S = 30


@pytest.fixture
async def clinic(session_factory: SessionFactory) -> BookingClinic:
    return await build_booking_clinic(session_factory)


def request_for(clinic: BookingClinic, starts_at: datetime, **overrides: Any) -> AppointmentCreate:
    return AppointmentCreate.model_validate(
        {
            "patient_id": str(clinic.patient_id),
            "appointment_type_id": str(clinic.checkup_id),
            "dentist_id": str(clinic.dentist_a),
            "starts_at": starts_at.isoformat(),
            **overrides,
        }
    )


async def rows(session_factory: SessionFactory, clinic_id: uuid.UUID) -> list[Appointment]:
    async with session_factory() as session:
        result = await session.scalars(
            select(Appointment).where(Appointment.clinic_id == clinic_id).order_by(Appointment.id)
        )
        return list(result.all())


@pytest.fixture
def hold_before_insert(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], set[int]]:
    """Make the next ``parties`` bookings wait for each other after their calendar read.

    Returns the set of PostgreSQL backend pids that reached the barrier, so a test can prove the
    transactions were genuinely concurrent and on separate connections.
    """

    def install(parties: int) -> set[int]:
        barrier = asyncio.Barrier(parties)
        backends: set[int] = set()
        original = ReservationService._require_bookable

        async def held(session: AsyncSession, *args: Any) -> None:
            await original(session, *args)
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            backends.add(pid)
            async with asyncio.timeout(BARRIER_TIMEOUT_S):
                await barrier.wait()

        monkeypatch.setattr(ReservationService, "_require_bookable", staticmethod(held))
        return backends

    return install


async def gather_outcomes(calls: list[Awaitable[Any]]) -> list[Any]:
    return list(await asyncio.gather(*calls, return_exceptions=True))


@pytest.mark.parametrize("pattern", ["same_start", "overlapping_starts"])
async def test_twenty_concurrent_reservations_for_one_slot_book_exactly_once(
    pattern: str,
    session_factory: SessionFactory,
    clinic: BookingClinic,
    hold_before_insert: Callable[[int], set[int]],
) -> None:
    backends = hold_before_insert(N)
    service = ReservationService(session_factory)
    # 30-minute visits starting at 09:00 or 09:15 all overlap one another.
    starts = [
        clinic.at(DAY, 9, 15 * (i % 2) if pattern == "overlapping_starts" else 0) for i in range(N)
    ]

    outcomes = await gather_outcomes(
        [
            service.reserve(
                clinic.clinic_id, request_for(clinic, start), f"race-{i:02d}-{uuid.uuid4().hex}"
            )
            for i, start in enumerate(starts)
        ]
    )

    assert len(backends) == N  # N transactions open at once, each on its own connection
    wins = [o for o in outcomes if isinstance(o, Reservation)]
    losses = [o for o in outcomes if isinstance(o, BookingSlotTakenError)]
    unexpected = [o for o in outcomes if not isinstance(o, Reservation | BookingSlotTakenError)]
    assert unexpected == []
    assert (len(wins), len(losses)) == (1, N - 1)
    assert wins[0].appointment.status is AppointmentStatus.CONFIRMED
    stored = await rows(session_factory, clinic.clinic_id)
    assert [(r.id, r.status) for r in stored] == [
        (wins[0].appointment.id, AppointmentStatus.CONFIRMED)
    ]


async def test_twenty_concurrent_api_requests_for_one_slot_book_exactly_once(
    client_factory: ClientFactory,
    database_settings: Settings,
    session_factory: SessionFactory,
    clinic: BookingClinic,
) -> None:
    settings = database_settings.model_copy(update={"db_pool_size": N})
    headers = headers_for(settings, clinic.clinic_id, ClinicRole.STAFF)
    body = request_for(clinic, clinic.at(DAY, 10)).model_dump(mode="json")

    async with client_factory(settings) as client:

        async def post(i: int) -> httpx.Response:
            return await client.post(
                "/api/v1/appointments",
                json=body,
                headers={**headers, "Idempotency-Key": f"api-race-{i:02d}-{uuid.uuid4().hex}"},
            )

        responses = await asyncio.gather(*(post(i) for i in range(N)))

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * (N - 1)
    codes = {r.json()["error"]["code"] for r in responses if r.status_code == 409}
    assert codes == {"BOOKING_SLOT_TAKEN"}
    winner = next(r.json() for r in responses if r.status_code == 201)
    stored = await rows(session_factory, clinic.clinic_id)
    assert [(str(r.id), r.status) for r in stored] == [(winner["id"], AppointmentStatus.CONFIRMED)]


async def test_concurrent_replays_of_one_request_create_one_appointment(
    session_factory: SessionFactory,
    clinic: BookingClinic,
    hold_before_insert: Callable[[int], set[int]],
) -> None:
    parties = 10
    backends = hold_before_insert(parties)
    service = ReservationService(session_factory)
    key = f"retry-{uuid.uuid4().hex}"
    request = request_for(clinic, clinic.at(DAY, 11))

    outcomes = await gather_outcomes(
        [service.reserve(clinic.clinic_id, request, key) for _ in range(parties)]
    )

    assert len(backends) == parties
    assert all(isinstance(o, Reservation) for o in outcomes), outcomes
    reservations = [o for o in outcomes if isinstance(o, Reservation)]
    assert len({r.appointment.id for r in reservations}) == 1
    assert sorted(r.replayed for r in reservations) == [False] + [True] * (parties - 1)
    assert len(await rows(session_factory, clinic.clinic_id)) == 1


async def test_concurrent_different_bodies_under_one_key_book_once_and_conflict(
    session_factory: SessionFactory,
    clinic: BookingClinic,
    hold_before_insert: Callable[[int], set[int]],
) -> None:
    hold_before_insert(4)
    service = ReservationService(session_factory)
    key = f"shared-{uuid.uuid4().hex}"
    # Four non-overlapping times, so only the idempotency key can make them collide.
    starts = [clinic.at(DAY, 9), clinic.at(DAY, 9, 30), clinic.at(DAY, 10), clinic.at(DAY, 10, 30)]

    outcomes = await gather_outcomes(
        [service.reserve(clinic.clinic_id, request_for(clinic, s), key) for s in starts]
    )

    wins = [o for o in outcomes if isinstance(o, Reservation)]
    conflicts = [o for o in outcomes if isinstance(o, IdempotencyConflictError)]
    assert (len(wins), len(conflicts)) == (1, 3), outcomes
    stored = await rows(session_factory, clinic.clinic_id)
    assert [r.id for r in stored] == [wins[0].appointment.id]


async def test_reschedule_racing_a_new_booking_for_the_same_time(
    session_factory: SessionFactory,
    clinic: BookingClinic,
    hold_before_insert: Callable[[int], set[int]],
) -> None:
    service = ReservationService(session_factory)
    original = (
        await service.reserve(
            clinic.clinic_id, request_for(clinic, clinic.at(DAY, 9)), uuid.uuid4().hex
        )
    ).appointment
    target = clinic.at(DAY, 11)
    hold_before_insert(2)

    reschedule, booking = await gather_outcomes(
        [
            service.reschedule(clinic.clinic_id, original.id, target),
            service.reserve(clinic.clinic_id, request_for(clinic, target), uuid.uuid4().hex),
        ]
    )

    outcomes = [reschedule, booking]
    assert sum(isinstance(o, BookingSlotTakenError) for o in outcomes) == 1, outcomes
    stored = {r.id: r for r in await rows(session_factory, clinic.clinic_id)}
    active_at_target = [
        r
        for r in stored.values()
        if r.starts_at == target and r.status in ACTIVE_APPOINTMENT_STATUSES
    ]
    assert len(active_at_target) == 1
    if isinstance(reschedule, BookingSlotTakenError):
        # The losing reschedule rolled back completely: the original is still booked.
        assert stored[original.id].status is AppointmentStatus.CONFIRMED
        assert len(stored) == 2
    else:
        assert stored[original.id].status is AppointmentStatus.RESCHEDULED
        assert active_at_target[0].rescheduled_from_id == original.id


async def test_concurrent_changes_to_one_appointment_apply_once(
    session_factory: SessionFactory, clinic: BookingClinic
) -> None:
    service = ReservationService(session_factory)
    original = (
        await service.reserve(
            clinic.clinic_id, request_for(clinic, clinic.at(DAY, 9)), uuid.uuid4().hex
        )
    ).appointment
    # Nine reschedules to nine different bookable times (09:30 … 11:30), plus a cancel, at once.
    targets = [clinic.at(DAY, 9 + (i // 4), 15 * (i % 4)) for i in range(2, 11)]

    outcomes = await gather_outcomes(
        [
            *(service.reschedule(clinic.clinic_id, original.id, t) for t in targets),
            service.cancel(clinic.clinic_id, original.id),
        ]
    )

    applied = [o for o in outcomes if not isinstance(o, BaseException)]
    refused = [o for o in outcomes if isinstance(o, AppointmentNotActiveError)]
    assert (len(applied), len(refused)) == (1, len(outcomes) - 1), outcomes
    stored = await rows(session_factory, clinic.clinic_id)
    active = [r for r in stored if r.status in ACTIVE_APPOINTMENT_STATUSES]
    original_row = next(r for r in stored if r.id == original.id)
    if original_row.status is AppointmentStatus.CANCELLED:
        assert (len(stored), active) == (1, [])
    else:
        assert original_row.status is AppointmentStatus.RESCHEDULED
        assert len(stored) == 2
        assert [r.rescheduled_from_id for r in active] == [original.id]


async def test_released_connections_leave_no_open_transactions(
    session_factory: SessionFactory,
) -> None:
    """After the races above, nothing is left idle in a transaction holding locks."""
    async with session_factory() as session:
        stuck = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction' "
                "AND pid <> pg_backend_pid()"
            )
        )
    assert stuck == 0
