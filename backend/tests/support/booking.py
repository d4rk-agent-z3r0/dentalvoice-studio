# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""A self-contained clinic with a published calendar, for booking integration tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import Principal, issue_access_token
from app.domain.enums import ClinicRole, PatientType, SlotStatus
from app.models import (
    AppointmentSlot,
    AppointmentType,
    Clinic,
    Dentist,
    DentistSchedule,
    Patient,
)
from app.services.calendar import publish_slots

# A Monday far enough ahead that "now" never catches up with it.
FUTURE_MONDAY = date(2030, 1, 7)


@dataclass(frozen=True)
class BookingClinic:
    clinic_id: uuid.UUID
    timezone: str
    dentist_a: uuid.UUID  # 09:00-12:00 local, every day
    dentist_b: uuid.UUID  # 10:00-11:00 local, every day
    checkup_id: uuid.UUID  # 30 minutes
    cleaning_id: uuid.UUID  # 45 minutes
    patient_id: uuid.UUID

    def at(self, day: date, hour: int, minute: int = 0) -> datetime:
        """A clinic-local wall-clock time as a UTC instant."""
        local = datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(self.timezone))
        return local.astimezone(UTC)


async def build_booking_clinic(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    timezone: str = "Europe/London",
    first_day: date = FUTURE_MONDAY,
    days: int = 1,
) -> BookingClinic:
    label = uuid.uuid4().hex[:10]
    async with session_factory.begin() as session:
        clinic = Clinic(name=f"Booking Clinic {label}", slug=f"book-{label}", timezone=timezone)
        session.add(clinic)
        await session.flush()
        dentist_a = Dentist(clinic_id=clinic.id, display_name="Dr. Ada Example")
        dentist_b = Dentist(clinic_id=clinic.id, display_name="Dr. Bo Example")
        checkup = AppointmentType(
            clinic_id=clinic.id, code="checkup", name="Check-up", duration_minutes=30
        )
        cleaning = AppointmentType(
            clinic_id=clinic.id, code="hygiene_cleaning", name="Cleaning", duration_minutes=45
        )
        patient = Patient(
            clinic_id=clinic.id,
            first_name="Robin",
            last_name="Example",
            email=f"robin.{label}@example.com",
            patient_type=PatientType.NEW,
        )
        session.add_all([dentist_a, dentist_b, checkup, cleaning, patient])
        await session.flush()
        for weekday in range(7):
            session.add_all(
                [
                    DentistSchedule(
                        clinic_id=clinic.id,
                        dentist_id=dentist_a.id,
                        weekday=weekday,
                        start_local=time(9, 0),
                        end_local=time(12, 0),
                    ),
                    DentistSchedule(
                        clinic_id=clinic.id,
                        dentist_id=dentist_b.id,
                        weekday=weekday,
                        start_local=time(10, 0),
                        end_local=time(11, 0),
                    ),
                ]
            )
        await session.flush()
        await publish_slots(session, clinic.id, timezone, first_day, days)
        return BookingClinic(
            clinic_id=clinic.id,
            timezone=timezone,
            dentist_a=dentist_a.id,
            dentist_b=dentist_b.id,
            checkup_id=checkup.id,
            cleaning_id=cleaning.id,
            patient_id=patient.id,
        )


async def set_slot_status(
    session_factory: async_sessionmaker[AsyncSession],
    clinic: BookingClinic,
    dentist_id: uuid.UUID,
    starts_at: datetime,
    status: SlotStatus,
) -> None:
    async with session_factory.begin() as session:
        result = await session.execute(
            update(AppointmentSlot)
            .where(
                AppointmentSlot.clinic_id == clinic.clinic_id,
                AppointmentSlot.dentist_id == dentist_id,
                AppointmentSlot.starts_at == starts_at,
            )
            .values(status=status)
            .returning(AppointmentSlot.id)
        )
        assert len(result.all()) == 1, "no such slot"


def headers_for(settings: Settings, clinic_id: uuid.UUID, role: ClinicRole) -> dict[str, str]:
    token = issue_access_token(settings, Principal(uuid.uuid4(), clinic_id, role))
    return {"Authorization": f"Bearer {token}"}
