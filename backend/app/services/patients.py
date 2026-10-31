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
from app.repositories.appointments import AppointmentRepository
from app.repositories.clinics import ClinicRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.intake import IntakeRepository
from app.repositories.patients import PatientRepository
from app.schemas.intake import IntakeSnapshotData
from app.schemas.patient import (
    PatientConversationRead,
    PatientCreate,
    PatientDetail,
    PatientRead,
    PatientSnapshotSummary,
    PatientUpdate,
)
from app.services.booking.reservations import to_read

# Upper bounds for the lists on a patient profile; a synthetic patient has a handful of each.
PROFILE_CONVERSATIONS_LIMIT = 100
PROFILE_APPOINTMENTS_LIMIT = 100

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

    async def detail(self, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> PatientDetail:
        """The profile with its linked conversations, appointments and latest confirmed intake."""
        async with self._session_factory() as session:
            patient = await PatientRepository(session).get(clinic_id, patient_id)
            if patient is None:
                raise NotFoundError("Patient")
            clinic = await ClinicRepository(session).get(clinic_id)
            if clinic is None:
                raise NotFoundError("Clinic")
            conversations = await ConversationRepository(session).list_for_patient(
                clinic_id, patient_id, limit=PROFILE_CONVERSATIONS_LIMIT
            )
            snapshots = await IntakeRepository(session).snapshots_for_conversations(
                clinic_id, [c.id for c in conversations]
            )
            appointments = await AppointmentRepository(session).list_for_patient(
                clinic_id, patient_id, limit=PROFILE_APPOINTMENTS_LIMIT
            )
            confirmed = {s.conversation_id: s.confirmed_at for s in snapshots}
            latest = max(snapshots, key=lambda s: (s.confirmed_at, s.id), default=None)
            summary = None
            if latest is not None:
                data = IntakeSnapshotData.model_validate(latest.data)
                summary = PatientSnapshotSummary(
                    conversation_id=latest.conversation_id,
                    confirmed_at=latest.confirmed_at,
                    patient_type=data.patient_type,
                    preferred_contact_channel=data.preferred_contact_channel,
                    visit_reason=data.visit_reason,
                    requested_service=data.requested_service,
                    preferred_date=data.preferred_date,
                    preferred_time=data.preferred_time,
                )
            return PatientDetail(
                patient=PatientRead.model_validate(patient),
                conversations=[
                    PatientConversationRead(
                        id=c.id,
                        scenario_id=c.scenario_id,
                        state=c.state,
                        provider_mode=c.provider_mode,
                        turn_count=c.turn_count,
                        started_at=c.started_at,
                        ended_at=c.ended_at,
                        created_at=c.created_at,
                        snapshot_confirmed_at=confirmed.get(c.id),
                    )
                    for c in conversations
                ],
                appointments=[to_read(a, clinic.timezone) for a in appointments],
                latest_snapshot=summary,
            )

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
