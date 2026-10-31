# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ConversationState
from app.models import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> None:
        self._session.add(conversation)

    async def get(self, clinic_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.clinic_id == clinic_id, Conversation.id == conversation_id
        )
        return await self._session.scalar(stmt)

    async def get_for_update(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        """Row-locked read: serialises turn processing for one conversation."""
        stmt = (
            select(Conversation)
            .where(Conversation.clinic_id == clinic_id, Conversation.id == conversation_id)
            .with_for_update()
        )
        return await self._session.scalar(stmt)

    async def list(
        self,
        clinic_id: uuid.UUID,
        *,
        state: ConversationState | None = None,
        limit: int = 50,
    ) -> Sequence[Conversation]:
        stmt = select(Conversation).where(Conversation.clinic_id == clinic_id)
        if state is not None:
            stmt = stmt.where(Conversation.state == state)
        stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit)
        return (await self._session.scalars(stmt)).all()

    async def list_for_patient(
        self, clinic_id: uuid.UUID, patient_id: uuid.UUID, *, limit: int = 100
    ) -> Sequence[Conversation]:
        """Conversations linked to a patient (a completed call links one), newest first."""
        stmt = (
            select(Conversation)
            .where(Conversation.clinic_id == clinic_id, Conversation.patient_id == patient_id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def compare_and_set_state(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        expected_version: int,
        new_state: ConversationState,
        ended_at: datetime | None,
        started_at: datetime | None = None,
    ) -> int | None:
        """Optimistic state update. Returns the new version, or None if another writer won."""
        values: dict[str, object] = {
            "state": new_state,
            "state_version": Conversation.state_version + 1,
            "ended_at": ended_at,
        }
        if started_at is not None:
            values["started_at"] = started_at
        stmt = (
            update(Conversation)
            .where(
                Conversation.clinic_id == clinic_id,
                Conversation.id == conversation_id,
                Conversation.state_version == expected_version,
            )
            .values(values)
            .returning(Conversation.state_version)
            .execution_options(synchronize_session=False)
        )
        return await self._session.scalar(stmt)
