# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Milestone 2 acceptance: synthetic records are created, retrieved and updated via services."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.enums import ContactChannel, ConversationState, PatientStatus, PatientType
from app.domain.errors import DuplicatePatientError, NotFoundError
from app.models import SyntheticPersona, SyntheticScenario
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.conversations import ConversationService
from app.services.patients import PatientService
from tests.integration.conftest import ClinicFactory

pytestmark = pytest.mark.integration


def _patient(**overrides: object) -> PatientCreate:
    values: dict[str, object] = {
        "first_name": "Ava",
        "last_name": "Patel",
        "email": "ava.patel@example.com",
        "phone": "555-0142",
        "preferred_contact_channel": ContactChannel.EMAIL,
        "patient_type": PatientType.NEW,
        **overrides,
    }
    return PatientCreate.model_validate(values)


async def test_patient_create_get_list_update(
    session_factory: async_sessionmaker[AsyncSession], make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    service = PatientService(session_factory)

    created = await service.create(clinic.id, _patient())
    assert created.status is PatientStatus.PROSPECTIVE
    assert await service.get(clinic.id, created.id) == created

    updated = await service.update(
        clinic.id, created.id, PatientUpdate(phone="555-0150", status=PatientStatus.REGISTERED)
    )
    assert (updated.phone, updated.status, updated.email) == (
        "+1-555-0150",
        PatientStatus.REGISTERED,
        "ava.patel@example.com",
    )
    assert updated.updated_at >= created.updated_at

    assert [p.id for p in await service.list(clinic.id, query="pat")] == [created.id]
    assert await service.list(clinic.id, query="%") == []  # wildcards are matched literally


async def test_duplicate_contact_in_same_clinic_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    service = PatientService(session_factory)
    await service.create(clinic.id, _patient())

    with pytest.raises(DuplicatePatientError):
        await service.create(clinic.id, _patient(email="AVA.PATEL@example.com", phone=None))
    with pytest.raises(DuplicatePatientError):
        await service.create(clinic.id, _patient(email="other@example.com"))


async def test_missing_patient_is_not_found(
    session_factory: async_sessionmaker[AsyncSession], make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    with pytest.raises(NotFoundError):
        await PatientService(session_factory).get(clinic.id, uuid.uuid4())


async def test_conversation_is_created_for_a_scenario(
    session_factory: async_sessionmaker[AsyncSession], make_clinic: ClinicFactory
) -> None:
    clinic = await make_clinic()
    async with session_factory.begin() as session:
        persona = SyntheticPersona(
            clinic_id=clinic.id,
            first_name="Leo",
            last_name="Okafor",
            email="leo.okafor@example.org",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="Test persona.",
        )
        session.add(persona)
        await session.flush()
        scenario = SyntheticScenario(
            clinic_id=clinic.id,
            persona_id=persona.id,
            code="A",
            title="Routine cleaning",
            objective="Book a cleaning.",
            clips=["a-01"],
            expected={},
        )
        session.add(scenario)

    service = ConversationService(session_factory)
    conversation = await service.create(clinic.id, scenario.id, provider_mode=ProviderMode.MOCK)

    assert (conversation.state, conversation.state_version, conversation.turn_count) == (
        ConversationState.CREATED,
        1,
        0,
    )
    assert await service.get(clinic.id, conversation.id) == conversation
    assert [c.id for c in await service.list(clinic.id)] == [conversation.id]
