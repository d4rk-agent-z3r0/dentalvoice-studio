# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Database-level guarantees, exercised directly against PostgreSQL.

These bypass Pydantic and the services on purpose: the database must refuse bad data even when
application code is wrong.
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.errors import violated_constraint
from app.domain.enums import (
    AppointmentStatus,
    ConversationState,
    IntakeField,
    IntakeFieldStatus,
    PatientType,
    SlotStatus,
)
from app.models import (
    Appointment,
    AppointmentSlot,
    Base,
    Conversation,
    IntakeDraft,
    Patient,
    User,
)
from app.repositories.conversations import ConversationRepository
from tests.support.factories import BASE_TIME, ClinicGraph, build_clinic_graph

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def graph(session_factory: SessionFactory) -> ClinicGraph:
    return await build_clinic_graph(session_factory, uuid.uuid4().hex[:8])


async def _insert(session_factory: SessionFactory, *rows: Base) -> None:
    async with session_factory.begin() as session:
        for row in rows:
            session.add(row)
            await session.flush()


async def _assert_rejected(session_factory: SessionFactory, prefix: str, *rows: Base) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert(session_factory, *rows)
    name = violated_constraint(caught.value)
    assert name is not None
    assert name.startswith(prefix), name


def _appointment(
    graph: ClinicGraph, start_offset_min: int, minutes: int, **kw: object
) -> Appointment:
    start = BASE_TIME + timedelta(minutes=start_offset_min)
    values: dict[str, object] = {
        "clinic_id": graph.clinic_id,
        "patient_id": graph.patient_id,
        "dentist_id": graph.dentist_id,
        "appointment_type_id": graph.appointment_type_id,
        "starts_at": start,
        "ends_at": start + timedelta(minutes=minutes),
        "status": AppointmentStatus.CONFIRMED,
        "idempotency_key": f"key-{uuid.uuid4().hex}",
        "request_hash": "0" * 64,
        **kw,
    }
    return Appointment(**values)


# --- reserved contact values -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("email", "phone", "constraint"),
    [
        ("someone@gmail.com", None, "ck_patients_email_reserved"),
        ("a@example.co.uk", None, "ck_patients_email_reserved"),
        (None, "+1-212-555-0142", "ck_patients_phone_reserved"),
        (None, "+1-555-0200", "ck_patients_phone_reserved"),
        (None, None, "ck_patients_has_contact"),
    ],
)
async def test_patient_contact_values_must_be_reserved(
    session_factory: SessionFactory,
    graph: ClinicGraph,
    email: str | None,
    phone: str | None,
    constraint: str,
) -> None:
    row = Patient(
        clinic_id=graph.clinic_id,
        first_name="X",
        last_name="Y",
        email=email,
        phone=phone,
        patient_type=PatientType.NEW,
    )
    await _assert_rejected(session_factory, constraint, row)


async def test_user_email_must_be_reserved(session_factory: SessionFactory) -> None:
    row = User(email="real.person@outlook.com", display_name="Nope")
    await _assert_rejected(session_factory, "ck_users_email_reserved", row)


# --- cross-tenant references are impossible -----------------------------------------------------


async def test_conversation_cannot_reference_another_clinics_scenario(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    other = await build_clinic_graph(session_factory, "other" + uuid.uuid4().hex[:6])
    row = Conversation(
        clinic_id=graph.clinic_id, scenario_id=other.scenario_id, provider_mode="mock"
    )
    await _assert_rejected(session_factory, "fk_conversations_clinic_id_scenario_id", row)


@pytest.mark.parametrize("foreign", ["patient_id", "dentist_id", "appointment_type_id"])
async def test_appointment_cannot_reference_another_clinics_rows(
    session_factory: SessionFactory, graph: ClinicGraph, foreign: str
) -> None:
    other = await build_clinic_graph(session_factory, "other" + uuid.uuid4().hex[:6])
    row = _appointment(graph, 0, 30, **{foreign: getattr(other, foreign)})
    await _assert_rejected(session_factory, f"fk_appointments_clinic_id_{foreign}", row)


async def test_intake_draft_cannot_attach_to_another_clinics_conversation(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    other = await build_clinic_graph(session_factory, "other" + uuid.uuid4().hex[:6])
    row = IntakeDraft(
        clinic_id=graph.clinic_id,
        conversation_id=other.conversation_id,
        field=IntakeField.FIRST_NAME,
        value="Ava",
        status=IntakeFieldStatus.PROVIDED,
    )
    await _assert_rejected(session_factory, "fk_intake_drafts_clinic_id_conversation_id", row)


# --- double booking ----------------------------------------------------------------------------


async def test_overlapping_active_appointments_for_one_dentist_are_rejected(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _insert(session_factory, _appointment(graph, 0, 30))
    await _assert_rejected(
        session_factory, "ex_appointments_dentist_no_overlap", _appointment(graph, 15, 30)
    )
    # Status "requested" is active too.
    await _assert_rejected(
        session_factory,
        "ex_appointments_dentist_no_overlap",
        _appointment(graph, 29, 30, status=AppointmentStatus.REQUESTED),
    )


async def test_adjacent_and_cancelled_appointments_do_not_conflict(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _insert(
        session_factory,
        _appointment(graph, 0, 30),
        _appointment(graph, 30, 30),  # half-open ranges: [09:00, 09:30) then [09:30, 10:00)
        _appointment(graph, 0, 30, status=AppointmentStatus.CANCELLED),
        _appointment(graph, 0, 30, status=AppointmentStatus.RESCHEDULED),
    )


async def test_idempotency_key_is_unique_per_clinic(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _insert(session_factory, _appointment(graph, 120, 30, idempotency_key="same-key-123"))
    await _assert_rejected(
        session_factory,
        "uq_appointments_clinic_id_idempotency_key",
        _appointment(graph, 240, 30, idempotency_key="same-key-123"),
    )
    other = await build_clinic_graph(session_factory, "other" + uuid.uuid4().hex[:6])
    await _insert(session_factory, _appointment(other, 120, 30, idempotency_key="same-key-123"))


async def test_slots_for_one_dentist_cannot_overlap(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    def slot(offset: int, status: SlotStatus = SlotStatus.OPEN) -> AppointmentSlot:
        start = BASE_TIME + timedelta(minutes=offset)
        return AppointmentSlot(
            clinic_id=graph.clinic_id,
            dentist_id=graph.dentist_id,
            starts_at=start,
            ends_at=start + timedelta(minutes=15),
            status=status,
        )

    await _insert(session_factory, slot(0), slot(15))
    await _assert_rejected(
        session_factory, "ex_appointment_slots_dentist_no_overlap", slot(10, SlotStatus.BLOCKED)
    )


# --- conversations and intake ------------------------------------------------------------------


async def test_ended_at_is_set_exactly_when_state_is_terminal(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    for state, ended in [
        (ConversationState.COMPLETED, None),
        (ConversationState.GREETING, BASE_TIME),
    ]:
        with pytest.raises(IntegrityError) as caught:
            async with session_factory.begin() as session:
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == graph.conversation_id)
                    .values(state=state, ended_at=ended)
                )
        assert violated_constraint(caught.value) == "ck_conversations_ended_iff_terminal"


async def test_state_update_with_a_stale_version_is_refused(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    async with session_factory.begin() as session:
        repo = ConversationRepository(session)
        assert (
            await repo.compare_and_set_state(
                graph.clinic_id,
                graph.conversation_id,
                expected_version=1,
                new_state=ConversationState.GREETING,
                ended_at=None,
                started_at=BASE_TIME,
            )
            == 2
        )
        stale = await repo.compare_and_set_state(
            graph.clinic_id,
            graph.conversation_id,
            expected_version=1,
            new_state=ConversationState.ABANDONED,
            ended_at=BASE_TIME,
        )
    assert stale is None


def _draft(graph: ClinicGraph, **kw: object) -> IntakeDraft:
    values: dict[str, object] = {
        "clinic_id": graph.clinic_id,
        "conversation_id": graph.conversation_id,
        "field": IntakeField.EMAIL,
        "value": "ava@example.com",
        "status": IntakeFieldStatus.PROVIDED,
        **kw,
    }
    return IntakeDraft(**values)


async def test_only_one_live_value_per_intake_field(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _insert(
        session_factory,
        _draft(graph, status=IntakeFieldStatus.SUPERSEDED),
        _draft(graph, status=IntakeFieldStatus.REJECTED, rejection_reason="not reserved"),
        _draft(graph),
    )
    await _assert_rejected(
        session_factory,
        "uq_intake_drafts_live_field",
        _draft(graph, status=IntakeFieldStatus.NEEDS_CONFIRMATION),
    )


@pytest.mark.parametrize(
    ("make", "constraint"),
    [
        (lambda g: _draft(g, status=IntakeFieldStatus.REJECTED), "ck_intake_drafts_rejection"),
        (lambda g: _draft(g, rejection_reason="why?"), "ck_intake_drafts_rejection"),
        (lambda g: _draft(g, confidence=Decimal("1.5")), "ck_intake_drafts_confidence"),
    ],
)
async def test_intake_draft_invariants(
    session_factory: SessionFactory,
    graph: ClinicGraph,
    make: Callable[[ClinicGraph], IntakeDraft],
    constraint: str,
) -> None:
    await _assert_rejected(session_factory, constraint, make(graph))
