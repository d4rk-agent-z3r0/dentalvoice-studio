# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppointmentType, Clinic


class ClinicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, clinic_id: uuid.UUID) -> Clinic | None:
        return await self._session.get(Clinic, clinic_id)

    async def appointment_types(self, clinic_id: uuid.UUID) -> Sequence[AppointmentType]:
        """Every type, active or not, ordered by name."""
        stmt = (
            select(AppointmentType)
            .where(AppointmentType.clinic_id == clinic_id)
            .order_by(AppointmentType.name, AppointmentType.id)
        )
        return (await self._session.scalars(stmt)).all()

    async def active_appointment_types(self, clinic_id: uuid.UUID) -> Sequence[AppointmentType]:
        stmt = (
            select(AppointmentType)
            .where(AppointmentType.clinic_id == clinic_id, AppointmentType.is_active.is_(True))
            .order_by(AppointmentType.code)
        )
        return (await self._session.scalars(stmt)).all()
