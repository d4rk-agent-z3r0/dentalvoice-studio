# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped dentist and appointment-type lookups. Every method takes ``clinic_id``."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppointmentType, Dentist


class DentistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, clinic_id: uuid.UUID, dentist_id: uuid.UUID) -> Dentist | None:
        stmt = select(Dentist).where(Dentist.clinic_id == clinic_id, Dentist.id == dentist_id)
        return await self._session.scalar(stmt)

    async def list_active(self, clinic_id: uuid.UUID) -> Sequence[Dentist]:
        stmt = (
            select(Dentist)
            .where(Dentist.clinic_id == clinic_id, Dentist.is_active.is_(True))
            .order_by(Dentist.display_name, Dentist.id)
        )
        return (await self._session.scalars(stmt)).all()


class AppointmentTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, clinic_id: uuid.UUID, appointment_type_id: uuid.UUID
    ) -> AppointmentType | None:
        stmt = select(AppointmentType).where(
            AppointmentType.clinic_id == clinic_id, AppointmentType.id == appointment_type_id
        )
        return await self._session.scalar(stmt)
