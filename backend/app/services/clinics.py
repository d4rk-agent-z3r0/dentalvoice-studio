# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Reference data of the caller's clinic, for booking screens."""

import uuid
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import NotFoundError
from app.repositories.clinics import ClinicRepository
from app.repositories.dentists import DentistRepository
from app.schemas.clinic import AppointmentTypeRead, ClinicRead, DentistRead
from app.services.booking.availability import Clock, utc_now


class ClinicService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def get(self, clinic_id: uuid.UUID) -> ClinicRead:
        async with self._session_factory() as session:
            clinics = ClinicRepository(session)
            clinic = await clinics.get(clinic_id)
            if clinic is None:
                raise NotFoundError("Clinic")
            types = await clinics.appointment_types(clinic_id)
            dentists = await DentistRepository(session).list_all(clinic_id)
            return ClinicRead(
                id=clinic.id,
                name=clinic.name,
                timezone=clinic.timezone,
                today=self._clock().astimezone(ZoneInfo(clinic.timezone)).date(),
                appointment_types=[AppointmentTypeRead.model_validate(t) for t in types],
                dentists=[DentistRead.model_validate(d) for d in dentists],
            )
