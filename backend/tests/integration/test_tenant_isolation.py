# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""A clinic can never read, list or change another clinic's records through the services.

Cross-clinic access fails closed with ``NotFoundError``: the same error as a record that does not
exist, so the response never confirms that another clinic's ID is real.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.errors import NotFoundError
from app.schemas.patient import PatientUpdate
from app.services.conversations import ConversationService
from app.services.patients import PatientService
from app.services.scenarios import ScenarioService
from tests.support.factories import ClinicGraph, build_clinic_graph

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def clinics(session_factory: SessionFactory) -> tuple[ClinicGraph, ClinicGraph]:
    suffix = uuid.uuid4().hex[:6]
    return (
        await build_clinic_graph(session_factory, f"a{suffix}"),
        await build_clinic_graph(session_factory, f"b{suffix}"),
    )


async def test_patients_are_invisible_across_clinics(
    session_factory: SessionFactory, clinics: tuple[ClinicGraph, ClinicGraph]
) -> None:
    a, b = clinics
    service = PatientService(session_factory)

    with pytest.raises(NotFoundError):
        await service.get(b.clinic_id, a.patient_id)
    assert a.patient_id not in {p.id for p in await service.list(b.clinic_id)}
    assert [p.id for p in await service.list(a.clinic_id)] == [a.patient_id]


async def test_patient_update_across_clinics_fails_and_changes_nothing(
    session_factory: SessionFactory, clinics: tuple[ClinicGraph, ClinicGraph]
) -> None:
    a, b = clinics
    service = PatientService(session_factory)
    before = await service.get(a.clinic_id, a.patient_id)

    with pytest.raises(NotFoundError):
        await service.update(b.clinic_id, a.patient_id, PatientUpdate(first_name="Hijacked"))

    assert await service.get(a.clinic_id, a.patient_id) == before


async def test_scenarios_and_personas_are_invisible_across_clinics(
    session_factory: SessionFactory, clinics: tuple[ClinicGraph, ClinicGraph]
) -> None:
    a, b = clinics
    service = ScenarioService(session_factory)

    with pytest.raises(NotFoundError):
        await service.get(b.clinic_id, a.scenario_id)
    with pytest.raises(NotFoundError):
        await service.get_persona(b.clinic_id, a.persona_id)
    assert [s.id for s in await service.list(b.clinic_id)] == [b.scenario_id]


async def test_conversation_cannot_be_started_from_another_clinics_scenario(
    session_factory: SessionFactory, clinics: tuple[ClinicGraph, ClinicGraph]
) -> None:
    a, b = clinics
    service = ConversationService(session_factory)

    with pytest.raises(NotFoundError):
        await service.create(b.clinic_id, a.scenario_id, provider_mode=ProviderMode.MOCK)
    with pytest.raises(NotFoundError):
        await service.get(b.clinic_id, a.conversation_id)
    assert a.conversation_id not in {c.id for c in await service.list(b.clinic_id)}


async def test_unknown_and_foreign_ids_are_indistinguishable(
    session_factory: SessionFactory, clinics: tuple[ClinicGraph, ClinicGraph]
) -> None:
    a, b = clinics
    service = PatientService(session_factory)

    with pytest.raises(NotFoundError) as foreign:
        await service.get(b.clinic_id, a.patient_id)
    with pytest.raises(NotFoundError) as unknown:
        await service.get(b.clinic_id, uuid.uuid4())

    assert str(foreign.value) == str(unknown.value)
