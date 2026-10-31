# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Load the synthetic demo world into the database. Safe to run repeatedly.

    uv run python -m app.demo.seed [--days 28]

Existing rows are matched by natural keys (clinic slug, appointment-type code, scenario code,
persona name) and brought in line with ``catalog.py``; nothing is duplicated. Slots are published
from today (clinic-local) for ``--days`` days.
"""

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database.session import create_engine, create_session_factory
from app.demo import catalog
from app.domain.enums import PatientStatus
from app.models import (
    AppointmentType,
    Clinic,
    ClinicUser,
    Dentist,
    DentistSchedule,
    Patient,
    SyntheticPersona,
    SyntheticScenario,
    User,
)
from app.repositories.patients import PatientRepository
from app.schemas.scenario import ScenarioExpectation
from app.services.calendar import publish_slots

log = get_logger(__name__)


@dataclass(frozen=True)
class SeedReport:
    clinics: int
    scenarios: int
    personas: int
    patients_created: int
    slots_created: int


def expectation(scenario: catalog.Scenario) -> ScenarioExpectation:
    return ScenarioExpectation(
        states=list(scenario.states),
        final_state=scenario.final_state,
        fields=scenario.fields,
        missing_fields=list(scenario.missing_fields),
        declined_fields=list(scenario.declined_fields),
        corrected_fields=list(scenario.corrected_fields),
        escalation_reason=scenario.escalation_reason,
    )


async def _clinic(session: AsyncSession, spec: catalog.Clinic) -> Clinic:
    clinic = await session.scalar(select(Clinic).where(Clinic.slug == spec.slug))
    if clinic is None:
        clinic = Clinic(slug=spec.slug, name=spec.name, timezone=spec.timezone)
        session.add(clinic)
    clinic.name, clinic.timezone = spec.name, spec.timezone
    await session.flush()
    return clinic


async def _dentists(session: AsyncSession, clinic_id: uuid.UUID, spec: catalog.Clinic) -> None:
    for dentist_spec in spec.dentists:
        dentist = await session.scalar(
            select(Dentist).where(
                Dentist.clinic_id == clinic_id, Dentist.display_name == dentist_spec.display_name
            )
        )
        if dentist is not None:
            continue  # schedules of an existing dentist are managed by the clinic, not the seed
        dentist = Dentist(clinic_id=clinic_id, display_name=dentist_spec.display_name)
        session.add(dentist)
        await session.flush()
        session.add_all(
            DentistSchedule(
                clinic_id=clinic_id,
                dentist_id=dentist.id,
                weekday=window.weekday,
                start_local=window.start,
                end_local=window.end,
            )
            for window in dentist_spec.hours
        )


async def _appointment_types(
    session: AsyncSession, clinic_id: uuid.UUID, spec: catalog.Clinic
) -> None:
    for type_spec in spec.appointment_types:
        row = await session.scalar(
            select(AppointmentType).where(
                AppointmentType.clinic_id == clinic_id, AppointmentType.code == type_spec.code
            )
        )
        if row is None:
            row = AppointmentType(clinic_id=clinic_id, code=type_spec.code)
            session.add(row)
        row.name, row.duration_minutes = type_spec.name, type_spec.duration_minutes


async def _personas(
    session: AsyncSession, clinic_id: uuid.UUID, spec: catalog.Clinic
) -> tuple[dict[str, SyntheticPersona], int]:
    personas: dict[str, SyntheticPersona] = {}
    patients_created = 0
    for persona_spec in spec.personas:
        persona = await session.scalar(
            select(SyntheticPersona).where(
                SyntheticPersona.clinic_id == clinic_id,
                SyntheticPersona.first_name == persona_spec.first_name,
                SyntheticPersona.last_name == persona_spec.last_name,
            )
        )
        if persona is None:
            persona = SyntheticPersona(
                clinic_id=clinic_id,
                first_name=persona_spec.first_name,
                last_name=persona_spec.last_name,
            )
            session.add(persona)
        persona.email = persona_spec.email
        persona.phone = persona_spec.phone
        persona.preferred_contact_channel = persona_spec.preferred_contact_channel
        persona.patient_type = persona_spec.patient_type
        persona.background = persona_spec.background
        await session.flush()
        personas[persona_spec.key] = persona

        if persona_spec.existing_patient:
            existing = await PatientRepository(session).find_by_contact(
                clinic_id, email=persona_spec.email, phone=persona_spec.phone
            )
            if existing is None:
                session.add(
                    Patient(
                        clinic_id=clinic_id,
                        persona_id=persona.id,
                        first_name=persona_spec.first_name,
                        last_name=persona_spec.last_name,
                        email=persona_spec.email,
                        phone=persona_spec.phone,
                        preferred_contact_channel=persona_spec.preferred_contact_channel,
                        patient_type=persona_spec.patient_type,
                        status=PatientStatus.REGISTERED,
                    )
                )
                patients_created += 1
    return personas, patients_created


async def _scenarios(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    spec: catalog.Clinic,
    personas: dict[str, SyntheticPersona],
) -> None:
    for scenario_spec in spec.scenarios:
        row = await session.scalar(
            select(SyntheticScenario).where(
                SyntheticScenario.clinic_id == clinic_id,
                SyntheticScenario.code == scenario_spec.code,
            )
        )
        if row is None:
            row = SyntheticScenario(clinic_id=clinic_id, code=scenario_spec.code)
            session.add(row)
        row.persona_id = personas[scenario_spec.persona_key].id
        row.title = scenario_spec.title
        row.objective = scenario_spec.objective
        row.clips = [clip.id for clip in scenario_spec.clips]
        row.expected = expectation(scenario_spec).model_dump(mode="json")


async def _users(session: AsyncSession, clinics: dict[str, uuid.UUID]) -> None:
    for spec in catalog.DEMO_USERS:
        user = await session.scalar(select(User).where(User.email == spec.email))
        if user is None:
            user = User(email=spec.email, display_name=spec.display_name)
            session.add(user)
            await session.flush()
        for slug, role in spec.roles.items():
            membership = await session.scalar(
                select(ClinicUser).where(
                    ClinicUser.clinic_id == clinics[slug], ClinicUser.user_id == user.id
                )
            )
            if membership is None:
                session.add(ClinicUser(clinic_id=clinics[slug], user_id=user.id, role=role))
            else:
                membership.role = role


async def seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int = 28,
    today: date | None = None,
) -> SeedReport:
    catalog.clip_index()  # fail fast on duplicate clip IDs
    patients_created = slots_created = 0
    async with session_factory.begin() as session:
        clinic_ids: dict[str, uuid.UUID] = {}
        for spec in catalog.CLINICS:
            clinic = await _clinic(session, spec)
            clinic_ids[spec.slug] = clinic.id
            await _dentists(session, clinic.id, spec)
            await _appointment_types(session, clinic.id, spec)
            personas, created = await _personas(session, clinic.id, spec)
            patients_created += created
            await _scenarios(session, clinic.id, spec, personas)
            await session.flush()
            local_today = today or datetime.now(UTC).astimezone(ZoneInfo(spec.timezone)).date()
            slots_created += await publish_slots(
                session, clinic.id, spec.timezone, local_today, days
            )
        await _users(session, clinic_ids)
    return SeedReport(
        clinics=len(catalog.CLINICS),
        scenarios=sum(len(c.scenarios) for c in catalog.CLINICS),
        personas=sum(len(c.personas) for c in catalog.CLINICS),
        patients_created=patients_created,
        slots_created=slots_created,
    )


async def _main(days: int) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    try:
        report = await seed(create_session_factory(engine), days=days)
    finally:
        await engine.dispose()
    log.info("seed_complete", **report.__dict__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic DentalVoice demo data.")
    parser.add_argument("--days", type=int, default=28, help="days of slots to publish (1-90)")
    args = parser.parse_args()
    if not 1 <= args.days <= 90:
        parser.error("--days must be between 1 and 90")
    asyncio.run(_main(args.days))


if __name__ == "__main__":
    main()
