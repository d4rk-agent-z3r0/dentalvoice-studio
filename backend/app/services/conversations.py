# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Conversation records. Turn processing and state changes live in the orchestrator."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.domain.enums import ConversationState, Speaker
from app.domain.errors import NotFoundError
from app.models import Conversation
from app.repositories.conversations import ConversationRepository
from app.repositories.intake import EventRepository, IntakeRepository
from app.repositories.scenarios import ScenarioRepository
from app.repositories.turns import TurnRepository
from app.schemas.conversation import ConversationDetail, ConversationRead, EventRead, TurnRead
from app.schemas.intake import IntakeDraftRead, IntakeSnapshotData
from app.services.intake.service import IntakeService
from app.services.intake.stages import missing_fields


class ConversationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        clinic_id: uuid.UUID,
        scenario_id: uuid.UUID,
        *,
        provider_mode: ProviderMode,
        started_by_user_id: uuid.UUID | None = None,
    ) -> ConversationRead:
        async with self._session_factory.begin() as session:
            # Checked explicitly so another clinic's scenario reads as "not found", not as an
            # integrity error that would confirm it exists.
            if await ScenarioRepository(session).get(clinic_id, scenario_id) is None:
                raise NotFoundError("Scenario")
            conversation = Conversation(
                clinic_id=clinic_id,
                scenario_id=scenario_id,
                provider_mode=provider_mode,
                started_by_user_id=started_by_user_id,
            )
            ConversationRepository(session).add(conversation)
            await session.flush()
            await session.refresh(conversation)
            return ConversationRead.model_validate(conversation)

    async def get(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationRead:
        async with self._session_factory() as session:
            row = await ConversationRepository(session).get(clinic_id, conversation_id)
            if row is None:
                raise NotFoundError("Conversation")
            return ConversationRead.model_validate(row)

    async def list(
        self, clinic_id: uuid.UUID, *, state: ConversationState | None = None, limit: int = 50
    ) -> list[ConversationRead]:
        async with self._session_factory() as session:
            rows = await ConversationRepository(session).list(clinic_id, state=state, limit=limit)
            return [ConversationRead.model_validate(row) for row in rows]

    async def detail(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> ConversationDetail:
        async with self._session_factory() as session:
            row = await ConversationRepository(session).get(clinic_id, conversation_id)
            if row is None:
                raise NotFoundError("Conversation")
            turns = await TurnRepository(session).list(clinic_id, conversation_id)
            events = await EventRepository(session).list(clinic_id, conversation_id)
            intake = IntakeRepository(session)
            drafts = await intake.all_drafts(clinic_id, conversation_id)
            snapshot = await intake.snapshot(clinic_id, conversation_id)
            values = await IntakeService(session).live_values(clinic_id, conversation_id)
            return ConversationDetail(
                conversation=ConversationRead.model_validate(row),
                turns=[TurnRead.model_validate(t) for t in turns],
                events=[EventRead.model_validate(e) for e in events],
                intake=[IntakeDraftRead.model_validate(d) for d in drafts],
                missing_fields=missing_fields(values),
                snapshot=IntakeSnapshotData.model_validate(snapshot.data) if snapshot else None,
            )

    async def voice_progress(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> "VoiceProgress":
        """Where a scripted call stands: its clips and how many replies have been given.

        The next caller clip is the one after the last *answered* clip, so a turn that failed
        (no reply) is replayed rather than skipped. Derived from the database on every call, so
        it survives restarts and reconnects.
        """
        async with self._session_factory() as session:
            row = await ConversationRepository(session).get(clinic_id, conversation_id)
            if row is None:
                raise NotFoundError("Conversation")
            scenario = await ScenarioRepository(session).get(clinic_id, row.scenario_id)
            replies = await TurnRepository(session).count(
                clinic_id, conversation_id, Speaker.RECEPTIONIST
            )
            return VoiceProgress(
                state=row.state,
                clips=list(scenario.clips) if scenario else [],
                answered_clips=max(0, replies - 1),  # the greeting answers no clip
            )


@dataclass(frozen=True)
class VoiceProgress:
    state: ConversationState
    clips: list[str]
    answered_clips: int

    @property
    def next_clip(self) -> str | None:
        return self.clips[self.answered_clips] if self.answered_clips < len(self.clips) else None
