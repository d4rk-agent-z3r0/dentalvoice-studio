# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped patient queries. Every method takes ``clinic_id``; none commits."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import PatientStatus
from app.models import Patient


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, patient: Patient) -> None:
        self._session.add(patient)

    async def get(self, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> Patient | None:
        stmt = select(Patient).where(Patient.clinic_id == clinic_id, Patient.id == patient_id)
        return await self._session.scalar(stmt)

    async def get_for_update(self, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> Patient | None:
        stmt = (
            select(Patient)
            .where(Patient.clinic_id == clinic_id, Patient.id == patient_id)
            .with_for_update()
        )
        return await self._session.scalar(stmt)

    async def find_by_contact(
        self, clinic_id: uuid.UUID, *, email: str | None, phone: str | None
    ) -> Patient | None:
        matches = []
        if email is not None:
            matches.append(func.lower(Patient.email) == email.lower())
        if phone is not None:
            matches.append(Patient.phone == phone)
        if not matches:
            return None
        stmt = select(Patient).where(Patient.clinic_id == clinic_id, or_(*matches)).limit(1)
        return await self._session.scalar(stmt)

    async def list(
        self,
        clinic_id: uuid.UUID,
        *,
        query: str | None = None,
        status: PatientStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Patient]:
        stmt: Select[Patient] = select(Patient).where(Patient.clinic_id == clinic_id)
        if query:
            pattern = f"%{_escape_like(query.strip())}%"
            stmt = stmt.where(
                or_(
                    Patient.first_name.ilike(pattern, escape="\\"),
                    Patient.last_name.ilike(pattern, escape="\\"),
                    Patient.email.ilike(pattern, escape="\\"),
                )
            )
        if status is not None:
            stmt = stmt.where(Patient.status == status)
        stmt = stmt.order_by(Patient.last_name, Patient.first_name, Patient.id)
        result = await self._session.scalars(stmt.limit(limit).offset(offset))
        return result.all()
