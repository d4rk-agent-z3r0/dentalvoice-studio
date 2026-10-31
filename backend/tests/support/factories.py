# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Build a small, complete clinic graph for integration tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.enums import ContactChannel, PatientType
from app.models import (
    AppointmentType,
    Clinic,
    Conversation,
    Dentist,
    Patient,
    SyntheticPersona,
    SyntheticScenario,
)

# A fixed instant in the future, so constraint tests never depend on "now".
BASE_TIME = datetime(2030, 1, 7, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ClinicGraph:
    clinic_id: uuid.UUID
    dentist_id: uuid.UUID
    appointment_type_id: uuid.UUID
    persona_id: uuid.UUID
    scenario_id: uuid.UUID
    patient_id: uuid.UUID
    conversation_id: uuid.UUID


async def build_clinic_graph(
    session_factory: async_sessionmaker[AsyncSession], label: str = "x"
) -> ClinicGraph:
    """One clinic with a dentist, appointment type, persona, scenario, patient and conversation.

    Contact values are unique per call (the clinic id is mixed in), because patients are unique
    per clinic by email and phone.
    """
    async with session_factory.begin() as session:
        clinic = Clinic(
            name=f"Graph Clinic {label}",
            slug=f"graph-{uuid.uuid4().hex[:12]}",
            timezone="Europe/London",
        )
        session.add(clinic)
        await session.flush()
        dentist = Dentist(clinic_id=clinic.id, display_name="Dr. Test")
        appointment_type = AppointmentType(
            clinic_id=clinic.id, code="checkup", name="Check-up", duration_minutes=30
        )
        persona = SyntheticPersona(
            clinic_id=clinic.id,
            first_name="Test",
            last_name=label,
            email=f"persona.{label}@example.com",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="Integration test persona.",
        )
        session.add_all([dentist, appointment_type, persona])
        await session.flush()
        scenario = SyntheticScenario(
            clinic_id=clinic.id,
            persona_id=persona.id,
            code="A",
            title="Test scenario",
            objective="Test.",
            clips=[],
            expected={},
        )
        patient = Patient(
            clinic_id=clinic.id,
            first_name="Pat",
            last_name=label,
            email=f"patient.{label}@example.com",
            patient_type=PatientType.NEW,
        )
        session.add_all([scenario, patient])
        await session.flush()
        conversation = Conversation(
            clinic_id=clinic.id, scenario_id=scenario.id, provider_mode=ProviderMode.MOCK
        )
        session.add(conversation)
        await session.flush()
        return ClinicGraph(
            clinic_id=clinic.id,
            dentist_id=dentist.id,
            appointment_type_id=appointment_type.id,
            persona_id=persona.id,
            scenario_id=scenario.id,
            patient_id=patient.id,
            conversation_id=conversation.id,
        )
