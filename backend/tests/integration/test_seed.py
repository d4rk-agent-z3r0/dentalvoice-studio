# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.demo import catalog
from app.demo.seed import seed
from app.domain.enums import PatientStatus
from app.models import AppointmentSlot, Clinic, Patient, SyntheticScenario
from app.schemas.scenario import ScenarioExpectation
from app.services.scenarios import ScenarioService

pytestmark = pytest.mark.integration

MONDAY = date(2026, 11, 2)


async def _count(session: AsyncSession, stmt: object) -> int:
    return int(await session.scalar(stmt) or 0)  # type: ignore[call-overload]


async def test_seed_loads_the_catalogue_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed(session_factory, days=7, today=MONDAY)
    async with session_factory() as session:
        clinics = await _count(
            session,
            select(func.count())
            .select_from(Clinic)
            .where(Clinic.slug.in_([c.slug for c in catalog.CLINICS])),
        )
        scenarios = await _count(session, select(func.count()).select_from(SyntheticScenario))
        slots = await _count(session, select(func.count()).select_from(AppointmentSlot))

    second = await seed(session_factory, days=7, today=MONDAY)

    async with session_factory() as session:
        assert clinics == len(catalog.CLINICS)
        assert (
            await _count(session, select(func.count()).select_from(SyntheticScenario)) == scenarios
        )
        assert await _count(session, select(func.count()).select_from(AppointmentSlot)) == slots
    assert (second.patients_created, second.slots_created) == (0, 0)


async def test_seeded_scenarios_round_trip_through_the_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed(session_factory, days=7, today=MONDAY)
    async with session_factory() as session:
        clinic = await session.scalar(select(Clinic).where(Clinic.slug == "brightsmile"))
        assert clinic is not None
        rows = (
            await session.scalars(
                select(SyntheticScenario).where(SyntheticScenario.clinic_id == clinic.id)
            )
        ).all()

    scenarios = await ScenarioService(session_factory).list(clinic.id)
    assert [s.code for s in scenarios] == ["A", "B", "C", "D", "E"]
    by_code = {row.code: ScenarioExpectation.model_validate(row.expected) for row in rows}
    assert by_code["E"].final_state == "ESCALATED"
    assert by_code["C"].corrected_fields == ["email", "preferred_date"]
    assert scenarios[0].clips == [clip.id for clip in catalog.BRIGHTSMILE.scenarios[0].clips]


async def test_returning_personas_have_registered_patient_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed(session_factory, days=1, today=MONDAY)
    async with session_factory() as session:
        clinic = await session.scalar(select(Clinic).where(Clinic.slug == "brightsmile"))
        assert clinic is not None
        emails = set(
            (
                await session.scalars(
                    select(Patient.email).where(
                        Patient.clinic_id == clinic.id, Patient.status == PatientStatus.REGISTERED
                    )
                )
            ).all()
        )
    assert emails >= {"marcus.b@example.org", "noah.brightwater@example.com"}


async def test_slots_are_published_in_clinic_local_hours(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed(session_factory, days=7, today=MONDAY)
    async with session_factory() as session:
        clinic = await session.scalar(select(Clinic).where(Clinic.slug == "juniper-vale"))
        assert clinic is not None
        first = await session.scalar(
            select(func.min(AppointmentSlot.starts_at)).where(
                AppointmentSlot.clinic_id == clinic.id,
                func.date(func.timezone(clinic.timezone, AppointmentSlot.starts_at)) == MONDAY,
            )
        )
    assert first is not None
    # 08:00 in New York on 2 Nov 2026 (EST, UTC-5) is 13:00 UTC.
    assert (first.hour, first.minute) == (13, 0)
