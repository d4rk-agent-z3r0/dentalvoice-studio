# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import re
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import IntakeField, IntakeFieldStatus
from app.repositories.intake import EventRepository, IntakeRepository
from app.services.intake.fields import ValidationContext
from app.services.intake.service import IntakeChanges, IntakeService
from tests.support.factories import ClinicGraph, build_clinic_graph

pytestmark = pytest.mark.integration

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

F = IntakeField
SessionFactory = async_sessionmaker[AsyncSession]
CTX = ValidationContext(today=date(2026, 11, 2), service_codes=frozenset({"checkup"}))

COMPLETE = [
    (F.FIRST_NAME, "ava"),
    (F.LAST_NAME, "lindqvist"),
    (F.PATIENT_TYPE, "new"),
    (F.PREFERRED_CONTACT_CHANNEL, "email"),
    (F.EMAIL, "ava@example.com"),
    (F.PHONE, "555-0101"),
    (F.VISIT_REASON, "check-up"),
    (F.REQUESTED_SERVICE, "checkup"),
    (F.PREFERRED_DATE, "2026-11-04"),
    (F.PREFERRED_TIME, "09:30"),
]


@pytest.fixture
async def graph(session_factory: SessionFactory) -> ClinicGraph:
    return await build_clinic_graph(session_factory, uuid.uuid4().hex[:8])


async def _apply(
    session_factory: SessionFactory,
    graph: ClinicGraph,
    updates: list[tuple[IntakeField, str]],
    *,
    declined: list[IntakeField] | None = None,
    corrected: list[IntakeField] | None = None,
    confidence: float = 0.9,
) -> IntakeChanges:
    async with session_factory.begin() as session:
        return await IntakeService(session).apply(
            graph.clinic_id,
            graph.conversation_id,
            updates=updates,
            declined=declined or [],
            corrected=corrected or [],
            confidence=confidence,
            source_turn_id=None,
            ctx=CTX,
        )


async def _history(
    session_factory: SessionFactory, graph: ClinicGraph
) -> list[tuple[str, str | None, str]]:
    async with session_factory() as session:
        rows = await IntakeRepository(session).all_drafts(graph.clinic_id, graph.conversation_id)
    return [(r.field.value, r.value, r.status.value) for r in rows]


async def test_valid_values_are_normalised_and_invalid_ones_recorded_not_applied(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    changes = await _apply(
        session_factory, graph, [(F.FIRST_NAME, "ava"), (F.EMAIL, "ava@gmail.com")]
    )

    assert changes.accepted == [F.FIRST_NAME]
    assert F.EMAIL in changes.rejected
    async with session_factory() as session:
        live = await IntakeService(session).live_values(graph.clinic_id, graph.conversation_id)
    assert live == {F.FIRST_NAME: ("Ava", IntakeFieldStatus.PROVIDED)}
    assert ("email", "ava@gmail.com", "rejected") in await _history(session_factory, graph)


async def test_correction_supersedes_and_keeps_history(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _apply(session_factory, graph, [(F.EMAIL, "elena.fairbank@example.net")])
    changes = await _apply(
        session_factory, graph, [(F.EMAIL, "elena.fairbanks@example.net")], corrected=[F.EMAIL]
    )
    repeat = await _apply(session_factory, graph, [(F.EMAIL, "ELENA.FAIRBANKS@example.net")])

    assert changes.corrected == [F.EMAIL]
    assert repeat.unchanged == [F.EMAIL]  # same value after normalising
    assert await _history(session_factory, graph) == [
        ("email", "elena.fairbank@example.net", "superseded"),
        ("email", "elena.fairbanks@example.net", "provided"),
    ]


async def test_declined_contact_is_explicitly_not_provided(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    changes = await _apply(session_factory, graph, [], declined=[F.EMAIL, F.FIRST_NAME])

    assert changes.declined == [F.EMAIL]  # names cannot be declined
    async with session_factory() as session:
        live = await IntakeService(session).live_values(graph.clinic_id, graph.conversation_id)
        events = [
            e.type
            for e in await EventRepository(session).list(graph.clinic_id, graph.conversation_id)
        ]
    assert live == {F.EMAIL: (None, IntakeFieldStatus.NOT_PROVIDED)}
    assert events == ["field_declined", "decline_ignored"]  # recorded in request order


async def test_low_confidence_values_need_confirmation(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _apply(session_factory, graph, [(F.LAST_NAME, "Lindqvist")], confidence=0.4)
    async with session_factory() as session:
        live = await IntakeService(session).live_values(graph.clinic_id, graph.conversation_id)
    assert live[F.LAST_NAME] == ("Lindqvist", IntakeFieldStatus.NEEDS_CONFIRMATION)


async def test_events_never_contain_field_values(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _apply(session_factory, graph, [(F.EMAIL, "ava@example.com"), (F.PHONE, "212-555-1234")])
    async with session_factory() as session:
        events = await EventRepository(session).list(graph.clinic_id, graph.conversation_id)
    # The payloads carry ids; a random UUID can contain "212" by chance, so ids are removed first.
    text = _UUID.sub("<id>", repr([e.payload for e in events]))
    assert "ava@example.com" not in text
    assert "ava" not in text
    for fragment in ("212", "555", "1234"):
        assert fragment not in text
    assert {e.type for e in events} == {"field_proposed", "field_rejected"}


async def test_snapshot_requires_a_complete_intake_and_records_provenance(
    session_factory: SessionFactory, graph: ClinicGraph
) -> None:
    await _apply(session_factory, graph, COMPLETE[:-1])
    with pytest.raises(ValueError, match="incomplete"):
        async with session_factory.begin() as session:
            await IntakeService(session).create_snapshot(
                graph.clinic_id, graph.conversation_id, datetime.now(UTC)
            )

    await _apply(session_factory, graph, COMPLETE[-1:])
    async with session_factory.begin() as session:
        service = IntakeService(session)
        confirmed = await service.confirm_all(graph.clinic_id, graph.conversation_id)
        snapshot = await service.create_snapshot(
            graph.clinic_id, graph.conversation_id, datetime.now(UTC)
        )
        live = await service.live(graph.clinic_id, graph.conversation_id)

    assert confirmed == len(COMPLETE)
    assert (snapshot.first_name, snapshot.preferred_date, snapshot.phone) == (
        "Ava",
        date(2026, 11, 4),
        "+1-555-0101",
    )
    assert snapshot.provenance == {name: draft.id for name, draft in live.items()}
    assert {d.status for d in live.values()} == {IntakeFieldStatus.CONFIRMED}
