# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Transactional reservations: book, cancel, reschedule (ADR-0004).

Rules that make double booking impossible and retries safe:

* The database decides overlap. The insert itself is the check: the exclusion constraint
  ``ex_appointments_dentist_no_overlap`` rejects a second active appointment for the same dentist
  and time, whichever transaction gets there second, at any isolation level. There is no
  application-level "is it free?" read that a concurrent request could race past.
* ``UNIQUE (clinic_id, idempotency_key)`` makes a retried request create at most one row. A request
  that loses a race on either constraint looks its key up again *after* the winner committed, so a
  concurrent replay of the same request returns the original rather than an error.
* Each method is one transaction, and a result is built only after that transaction has
  committed: nothing is reported as booked, cancelled or rescheduled before the database said so.
* Two inserts racing on the exclusion constraint could deadlock (each waiting for the other's
  uncommitted row). Bookings for one dentist therefore take a transaction-scoped advisory lock
  just before inserting, so they queue instead; the constraint still decides who wins. As a
  safety net, a transaction PostgreSQL aborts anyway (deadlock or serialization failure) is
  retried a bounded number of times (``app.database.retry``), and the loser still gets
  ``BOOKING_SLOT_TAKEN``, never a raw database error.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.errors import violated_constraint
from app.database.retry import retry_transaction
from app.domain.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus
from app.domain.errors import (
    AppointmentNotActiveError,
    BookingSlotTakenError,
    IdempotencyConflictError,
    NotFoundError,
    SlotUnavailableError,
)
from app.models import Appointment, Clinic
from app.repositories.appointments import AppointmentRepository
from app.repositories.clinics import ClinicRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.dentists import AppointmentTypeRepository, DentistRepository
from app.repositories.patients import PatientRepository
from app.repositories.slots import SlotRepository
from app.schemas.booking import AppointmentCreate, AppointmentRead
from app.services.booking.availability import Clock, utc_now
from app.services.booking.idempotency import (
    is_client_key,
    request_hash,
    reschedule_key,
)
from app.services.booking.slots import Block, covers_exactly, local_days_window

OVERLAP_CONSTRAINT = "ex_appointments_dentist_no_overlap"
IDEMPOTENCY_CONSTRAINT = "uq_appointments_clinic_id_idempotency_key"
TRANSACTION_ATTEMPTS = 4  # one try plus up to three retries after a deadlock


@dataclass(frozen=True)
class Reservation:
    appointment: AppointmentRead
    replayed: bool  # True when an earlier request with the same key and body created it


def to_read(appointment: Appointment, timezone: str) -> AppointmentRead:
    zone = ZoneInfo(timezone)
    return AppointmentRead(
        id=appointment.id,
        patient_id=appointment.patient_id,
        dentist_id=appointment.dentist_id,
        appointment_type_id=appointment.appointment_type_id,
        conversation_id=appointment.conversation_id,
        rescheduled_from_id=appointment.rescheduled_from_id,
        status=appointment.status,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        starts_at_local=appointment.starts_at.astimezone(zone).isoformat(),
        ends_at_local=appointment.ends_at.astimezone(zone).isoformat(),
        timezone=timezone,
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
    )


async def _clinic(session: AsyncSession, clinic_id: uuid.UUID) -> Clinic:
    clinic = await ClinicRepository(session).get(clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic")
    return clinic


class ReservationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = utc_now,
        *,
        attempts: int = TRANSACTION_ATTEMPTS,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._attempts = attempts

    async def reserve(
        self, clinic_id: uuid.UUID, request: AppointmentCreate, idempotency_key: str
    ) -> Reservation:
        """Book ``request`` as ``confirmed``. Same key + same body returns the original booking."""
        if not is_client_key(idempotency_key):
            raise ValueError("invalid idempotency key")
        digest = request_hash(request.model_dump(mode="json"))
        replay = await self._replay(clinic_id, idempotency_key, digest)
        if replay is not None:
            return replay

        async def transaction() -> tuple[Appointment, str]:
            async with self._session_factory.begin() as session:
                appointment = await self._insert(
                    session, clinic_id, request, idempotency_key, digest
                )
                return appointment, (await _clinic(session, clinic_id)).timezone

        try:
            appointment, timezone = await retry_transaction(transaction, attempts=self._attempts)
            # Committed. Only from here on may the booking be reported as confirmed.
        except IntegrityError as error:
            # Whoever beat us has committed by now (PostgreSQL waits for the conflicting
            # transaction before raising), so a fresh read sees its row if it used our key.
            replay = await self._replay(clinic_id, idempotency_key, digest)
            if replay is not None:
                return replay
            if violated_constraint(error) == OVERLAP_CONSTRAINT:
                raise BookingSlotTakenError from error
            raise
        return Reservation(to_read(appointment, timezone), replayed=False)

    async def cancel(self, clinic_id: uuid.UUID, appointment_id: uuid.UUID) -> AppointmentRead:
        async with self._session_factory.begin() as session:
            appointment = await self._lock_active(session, clinic_id, appointment_id)
            appointment.status = AppointmentStatus.CANCELLED
            await session.flush()
            await session.refresh(appointment)
            timezone = (await _clinic(session, clinic_id)).timezone
        return to_read(appointment, timezone)

    async def reschedule(
        self, clinic_id: uuid.UUID, appointment_id: uuid.UUID, starts_at: datetime
    ) -> AppointmentRead:
        """Atomically replace an active appointment with one at ``starts_at`` (same dentist, type
        and patient). If the new time cannot be booked, the original is left exactly as it was."""
        now = self._clock()

        async def transaction() -> tuple[Appointment, str]:
            async with self._session_factory.begin() as session:
                repository = AppointmentRepository(session)
                old = await self._lock_active(session, clinic_id, appointment_id)
                appointment_type = await AppointmentTypeRepository(session).get(
                    clinic_id, old.appointment_type_id
                )
                if appointment_type is None:  # impossible: composite foreign key
                    raise NotFoundError("Appointment type")
                ends_at = starts_at + timedelta(minutes=appointment_type.duration_minutes)
                await self._require_bookable(
                    session, clinic_id, old.dentist_id, starts_at, ends_at, now
                )
                await repository.lock_dentist_calendar(clinic_id, old.dentist_id)
                # Release the old time first, so the new one may overlap it (e.g. 15 minutes later).
                old.status = AppointmentStatus.RESCHEDULED
                await session.flush()
                new = Appointment(
                    clinic_id=clinic_id,
                    patient_id=old.patient_id,
                    dentist_id=old.dentist_id,
                    appointment_type_id=old.appointment_type_id,
                    conversation_id=old.conversation_id,
                    rescheduled_from_id=old.id,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    status=AppointmentStatus.CONFIRMED,
                    idempotency_key=reschedule_key(old.id),
                    request_hash=request_hash(
                        {"reschedule_of": str(old.id), "starts_at": starts_at.isoformat()}
                    ),
                )
                repository.add(new)
                await session.flush()
                await session.refresh(new)
                return new, (await _clinic(session, clinic_id)).timezone

        try:
            new, timezone = await retry_transaction(transaction, attempts=self._attempts)
        except IntegrityError as error:
            if violated_constraint(error) == OVERLAP_CONSTRAINT:
                raise BookingSlotTakenError from error
            raise
        return to_read(new, timezone)

    async def list(
        self,
        clinic_id: uuid.UUID,
        *,
        first_day: date | None = None,
        last_day: date | None = None,
        status: AppointmentStatus | None = None,
        limit: int = 100,
    ) -> list[AppointmentRead]:
        """Appointments starting on clinic-local days ``first_day``..``last_day`` (inclusive)."""
        async with self._session_factory() as session:
            timezone = (await _clinic(session, clinic_id)).timezone
            starts_from = (
                local_days_window(first_day, 1, timezone).start if first_day is not None else None
            )
            starts_before = (
                local_days_window(last_day, 1, timezone).end if last_day is not None else None
            )
            rows = await AppointmentRepository(session).list(
                clinic_id,
                starts_from=starts_from,
                starts_before=starts_before,
                status=status,
                limit=limit,
            )
            return [to_read(row, timezone) for row in rows]

    async def _replay(
        self, clinic_id: uuid.UUID, idempotency_key: str, digest: str
    ) -> Reservation | None:
        async with self._session_factory() as session:
            existing = await AppointmentRepository(session).get_by_idempotency_key(
                clinic_id, idempotency_key
            )
            if existing is None:
                return None
            if existing.request_hash != digest:
                raise IdempotencyConflictError
            timezone = (await _clinic(session, clinic_id)).timezone
            return Reservation(to_read(existing, timezone), replayed=True)

    async def _insert(
        self,
        session: AsyncSession,
        clinic_id: uuid.UUID,
        request: AppointmentCreate,
        idempotency_key: str,
        digest: str,
    ) -> Appointment:
        now = self._clock()
        if await PatientRepository(session).get(clinic_id, request.patient_id) is None:
            raise NotFoundError("Patient")
        appointment_type = await AppointmentTypeRepository(session).get(
            clinic_id, request.appointment_type_id
        )
        if appointment_type is None or not appointment_type.is_active:
            raise NotFoundError("Appointment type")
        if await DentistRepository(session).get(clinic_id, request.dentist_id) is None:
            raise NotFoundError("Dentist")
        if request.conversation_id is not None and (
            await ConversationRepository(session).get(clinic_id, request.conversation_id) is None
        ):
            raise NotFoundError("Conversation")
        ends_at = request.starts_at + timedelta(minutes=appointment_type.duration_minutes)
        await self._require_bookable(
            session, clinic_id, request.dentist_id, request.starts_at, ends_at, now
        )
        await AppointmentRepository(session).lock_dentist_calendar(clinic_id, request.dentist_id)
        appointment = Appointment(
            clinic_id=clinic_id,
            patient_id=request.patient_id,
            dentist_id=request.dentist_id,
            appointment_type_id=request.appointment_type_id,
            conversation_id=request.conversation_id,
            starts_at=request.starts_at,
            ends_at=ends_at,
            status=AppointmentStatus.CONFIRMED,
            idempotency_key=idempotency_key,
            request_hash=digest,
        )
        AppointmentRepository(session).add(appointment)
        await session.flush()  # the exclusion and unique constraints are checked here
        await session.refresh(appointment)
        return appointment

    @staticmethod
    async def _require_bookable(
        session: AsyncSession,
        clinic_id: uuid.UUID,
        dentist_id: uuid.UUID,
        starts_at: datetime,
        ends_at: datetime,
        now: datetime,
    ) -> None:
        """The time is in the future and exactly tiled by open published slots of an active
        dentist. Whether another appointment holds it is left to the exclusion constraint."""
        if starts_at <= now:
            raise SlotUnavailableError("That time is in the past.")
        dentist = await DentistRepository(session).get(clinic_id, dentist_id)
        if dentist is None or not dentist.is_active:
            raise SlotUnavailableError("That dentist is not taking bookings.")
        slots = await SlotRepository(session).overlapping_for_share(
            clinic_id, dentist_id, starts_at, ends_at
        )
        blocks: Sequence[Block] = [
            Block(s.dentist_id, s.starts_at, s.ends_at, s.status) for s in slots
        ]
        if not covers_exactly(blocks, starts_at, ends_at):
            raise SlotUnavailableError("That time is not open for booking.")

    @staticmethod
    async def _lock_active(
        session: AsyncSession, clinic_id: uuid.UUID, appointment_id: uuid.UUID
    ) -> Appointment:
        appointment = await AppointmentRepository(session).get_for_update(clinic_id, appointment_id)
        if appointment is None:
            raise NotFoundError("Appointment")
        if appointment.status not in ACTIVE_APPOINTMENT_STATUSES:
            raise AppointmentNotActiveError
        return appointment
