# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Availability: open published slots minus active appointments (ADR-0004 revision).

Availability is advisory. It is read without locks, so a listed time can be taken a moment later;
the booking itself is decided by the database (see ``reservations``).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError
from app.repositories.appointments import AppointmentRepository
from app.repositories.clinics import ClinicRepository
from app.repositories.dentists import AppointmentTypeRepository, DentistRepository
from app.repositories.slots import SlotRepository
from app.schemas.booking import AvailabilityRead, AvailableSlotRead
from app.services.booking.slots import Block, bookable_starts, local_days_window

MAX_DAYS = 14
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class AvailabilityService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def find(
        self,
        clinic_id: uuid.UUID,
        appointment_type_id: uuid.UUID,
        first_day: date,
        days: int = 1,
    ) -> AvailabilityRead:
        """Bookable start times for one appointment type over ``days`` clinic-local days."""
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f"days must be between 1 and {MAX_DAYS}")
        async with self._session_factory() as session:
            clinic = await ClinicRepository(session).get(clinic_id)
            if clinic is None:
                raise NotFoundError("Clinic")
            appointment_type = await AppointmentTypeRepository(session).get(
                clinic_id, appointment_type_id
            )
            if appointment_type is None or not appointment_type.is_active:
                raise NotFoundError("Appointment type")
            duration = timedelta(minutes=appointment_type.duration_minutes)
            window = local_days_window(first_day, days, clinic.timezone)
            # A run may start inside the window and finish just after it.
            slots = await SlotRepository(session).open_starting_between(
                clinic_id, window.start, window.end + duration
            )
            busy = await AppointmentRepository(session).active_overlapping(
                clinic_id, window.start, window.end + duration
            )
            names = {
                d.id: d.display_name
                for d in await DentistRepository(session).list_active(clinic_id)
            }

        options = bookable_starts(
            (Block(s.dentist_id, s.starts_at, s.ends_at, s.status) for s in slots),
            (Block(a.dentist_id, a.starts_at, a.ends_at) for a in busy),
            duration,
            window=window,
            after=self._clock(),
        )
        zone = ZoneInfo(clinic.timezone)
        return AvailabilityRead(
            appointment_type_id=appointment_type.id,
            duration_minutes=appointment_type.duration_minutes,
            timezone=clinic.timezone,
            first_day=first_day,
            days=days,
            slots=[
                AvailableSlotRead(
                    dentist_id=option.dentist_id,
                    dentist_name=names[option.dentist_id],
                    starts_at=option.starts_at.astimezone(UTC),
                    ends_at=option.ends_at.astimezone(UTC),
                    starts_at_local=option.starts_at.astimezone(zone).isoformat(),
                    ends_at_local=option.ends_at.astimezone(zone).isoformat(),
                )
                for option in options
                if option.dentist_id in names
            ],
        )
