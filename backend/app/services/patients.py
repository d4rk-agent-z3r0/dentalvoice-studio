# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Patient use cases. Each method is one transaction; ``clinic_id`` always comes from the caller's
authenticated context, never from request data."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.errors import violated_constraint
from app.domain.enums import PatientStatus
from app.domain.errors import DuplicatePatientError, NotFoundError
from app.models import Patient
from app.repositories.patients import PatientRepository
from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate

_DUPLICATE_CONSTRAINTS = frozenset({"uq_patients_clinic_email", "uq_patients_clinic_phone"})


class PatientService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, clinic_id: uuid.UUID, data: PatientCreate) -> PatientRead:
        try:
            async with self._session_factory.begin() as session:
                patient = Patient(clinic_id=clinic_id, **data.model_dump())
                PatientRepository(session).add(patient)
                await session.flush()
                await session.refresh(patient)
                return PatientRead.model_validate(patient)
        except IntegrityError as error:
            if violated_constraint(error) in _DUPLICATE_CONSTRAINTS:
                raise DuplicatePatientError from error
            raise

    async def get(self, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> PatientRead:
        async with self._session_factory() as session:
            patient = await PatientRepository(session).get(clinic_id, patient_id)
            if patient is None:
                raise NotFoundError("Patient")
            return PatientRead.model_validate(patient)

    async def list(
        self,
        clinic_id: uuid.UUID,
        *,
        query: str | None = None,
        status: PatientStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PatientRead]:
        async with self._session_factory() as session:
            rows = await PatientRepository(session).list(
                clinic_id, query=query, status=status, limit=limit, offset=offset
            )
            return [PatientRead.model_validate(row) for row in rows]

    async def update(
        self, clinic_id: uuid.UUID, patient_id: uuid.UUID, changes: PatientUpdate
    ) -> PatientRead:
        try:
            async with self._session_factory.begin() as session:
                patient = await PatientRepository(session).get_for_update(clinic_id, patient_id)
                if patient is None:
                    raise NotFoundError("Patient")
                for field, value in changes.model_dump(exclude_unset=True).items():
                    setattr(patient, field, value)
                await session.flush()
                await session.refresh(patient)
                return PatientRead.model_validate(patient)
        except IntegrityError as error:
            if violated_constraint(error) in _DUPLICATE_CONSTRAINTS:
                raise DuplicatePatientError from error
            raise
