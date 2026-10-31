# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import LIVE_INTAKE_STATUSES, IntakeFieldStatus
from app.models import ConversationEvent, IntakeDraft, IntakeSnapshot


class IntakeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, draft: IntakeDraft) -> None:
        self._session.add(draft)

    async def live_drafts(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Sequence[IntakeDraft]:
        stmt = select(IntakeDraft).where(
            IntakeDraft.clinic_id == clinic_id,
            IntakeDraft.conversation_id == conversation_id,
            IntakeDraft.status.in_(LIVE_INTAKE_STATUSES),
        )
        return (await self._session.scalars(stmt)).all()

    async def all_drafts(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Sequence[IntakeDraft]:
        stmt = (
            select(IntakeDraft)
            .where(
                IntakeDraft.clinic_id == clinic_id, IntakeDraft.conversation_id == conversation_id
            )
            .order_by(IntakeDraft.created_at, IntakeDraft.id)
        )
        return (await self._session.scalars(stmt)).all()

    async def set_status(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        from_statuses: Iterable[IntakeFieldStatus],
        to_status: IntakeFieldStatus,
    ) -> int:
        stmt = (
            update(IntakeDraft)
            .where(
                IntakeDraft.clinic_id == clinic_id,
                IntakeDraft.conversation_id == conversation_id,
                IntakeDraft.status.in_(list(from_statuses)),
            )
            .values(status=to_status)
            .returning(IntakeDraft.id)
            .execution_options(synchronize_session=False)
        )
        return len((await self._session.scalars(stmt)).all())

    def add_snapshot(self, snapshot: IntakeSnapshot) -> None:
        self._session.add(snapshot)

    async def snapshot(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> IntakeSnapshot | None:
        stmt = select(IntakeSnapshot).where(
            IntakeSnapshot.clinic_id == clinic_id, IntakeSnapshot.conversation_id == conversation_id
        )
        return await self._session.scalar(stmt)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        type_: str,
        payload: dict[str, Any] | None = None,
    ) -> ConversationEvent:
        event = ConversationEvent(
            clinic_id=clinic_id, conversation_id=conversation_id, type=type_, payload=payload or {}
        )
        self._session.add(event)
        return event

    async def list(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Sequence[ConversationEvent]:
        stmt = (
            select(ConversationEvent)
            .where(
                ConversationEvent.clinic_id == clinic_id,
                ConversationEvent.conversation_id == conversation_id,
            )
            .order_by(ConversationEvent.created_at, ConversationEvent.id)
        )
        return (await self._session.scalars(stmt)).all()
