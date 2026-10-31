# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Insert conversation history directly, for read-API tests that need exact, known rows."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.enums import ContactChannel, ConversationState, PatientStatus, PatientType, Speaker
from app.models import (
    Conversation,
    ConversationTurn,
    IntakeSnapshot,
    Patient,
    SyntheticPersona,
    SyntheticScenario,
)
from app.repositories.intake import EventRepository

SessionFactory = async_sessionmaker[AsyncSession]


async def add_scenario(
    session_factory: SessionFactory, clinic_id: uuid.UUID, code: str = "A"
) -> uuid.UUID:
    label = uuid.uuid4().hex[:8]
    async with session_factory.begin() as session:
        persona = SyntheticPersona(
            clinic_id=clinic_id,
            first_name="Persona",
            last_name=label,
            email=f"persona.{label}@example.com",
            preferred_contact_channel=ContactChannel.EMAIL,
            patient_type=PatientType.NEW,
            background="Read-API test persona.",
        )
        session.add(persona)
        await session.flush()
        scenario = SyntheticScenario(
            clinic_id=clinic_id,
            persona_id=persona.id,
            code=code,
            title="Read-API test scenario",
            objective="Test.",
            clips=[],
            expected={},
        )
        session.add(scenario)
        await session.flush()
        return scenario.id


async def add_patient(
    session_factory: SessionFactory,
    clinic_id: uuid.UUID,
    first_name: str,
    last_name: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    status: PatientStatus = PatientStatus.PROSPECTIVE,
) -> uuid.UUID:
    async with session_factory.begin() as session:
        patient = Patient(
            clinic_id=clinic_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            patient_type=PatientType.NEW,
            status=status,
        )
        session.add(patient)
        await session.flush()
        return patient.id


@dataclass(frozen=True)
class TurnTimings:
    stt_ms: int | None = None
    llm_ms: int | None = None
    tts_ms: int | None = None
    total_ms: int | None = None


async def add_conversation(
    session_factory: SessionFactory,
    clinic_id: uuid.UUID,
    scenario_id: uuid.UUID,
    *,
    state: ConversationState,
    created_at: datetime,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    patient_id: uuid.UUID | None = None,
    provider_mode: ProviderMode = ProviderMode.MOCK,
    turns: list[TurnTimings] | None = None,
    escalation_reason: str | None = None,
) -> uuid.UUID:
    """One conversation with optional receptionist turns carrying the given timings."""
    async with session_factory.begin() as session:
        conversation = Conversation(
            clinic_id=clinic_id,
            scenario_id=scenario_id,
            patient_id=patient_id,
            state=state,
            provider_mode=provider_mode,
            turn_count=len(turns or []),
            started_at=started_at,
            ended_at=ended_at,
            created_at=created_at,
        )
        session.add(conversation)
        await session.flush()
        for seq, timing in enumerate(turns or [], start=1):
            session.add(
                ConversationTurn(
                    clinic_id=clinic_id,
                    conversation_id=conversation.id,
                    seq=seq,
                    speaker=Speaker.RECEPTIONIST,
                    text="Synthetic reply.",
                    stt_ms=timing.stt_ms,
                    llm_ms=timing.llm_ms,
                    tts_ms=timing.tts_ms,
                    total_ms=timing.total_ms,
                )
            )
        if escalation_reason is not None:
            EventRepository(session).record(
                clinic_id, conversation.id, "escalated", {"reason": escalation_reason}
            )
        return conversation.id


def snapshot_data(**overrides: Any) -> dict[str, Any]:
    """A valid ``IntakeSnapshotData`` payload, as stored (JSON types)."""
    return {
        "first_name": "Robin",
        "last_name": "Example",
        "patient_type": "new",
        "preferred_contact_channel": "email",
        "email": "robin@example.com",
        "phone": None,
        "visit_reason": "Routine cleaning",
        "requested_service": "hygiene_cleaning",
        "preferred_date": "2030-01-07",
        "preferred_time": "10:00:00",
        "provenance": {},
        **overrides,
    }


async def add_snapshot(
    session_factory: SessionFactory,
    clinic_id: uuid.UUID,
    conversation_id: uuid.UUID,
    confirmed_at: datetime,
    **data: Any,
) -> None:
    async with session_factory.begin() as session:
        session.add(
            IntakeSnapshot(
                clinic_id=clinic_id,
                conversation_id=conversation_id,
                data=snapshot_data(**data),
                confirmed_at=confirmed_at,
            )
        )
