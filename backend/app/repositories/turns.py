# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Speaker
from app.models import ConversationTurn


class TurnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, turn: ConversationTurn) -> None:
        self._session.add(turn)

    async def list(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID, *, last: int | None = None
    ) -> Sequence[ConversationTurn]:
        stmt = select(ConversationTurn).where(
            ConversationTurn.clinic_id == clinic_id,
            ConversationTurn.conversation_id == conversation_id,
        )
        if last is not None:
            stmt = stmt.order_by(ConversationTurn.seq.desc()).limit(last)
            return list(reversed((await self._session.scalars(stmt)).all()))
        return (await self._session.scalars(stmt.order_by(ConversationTurn.seq))).all()

    async def set_audio_timings(
        self,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        seq: int,
        *,
        tts_ms: int | None,
        total_ms: int | None,
    ) -> None:
        await self._session.execute(
            update(ConversationTurn)
            .where(
                ConversationTurn.clinic_id == clinic_id,
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.seq == seq,
                ConversationTurn.speaker == Speaker.RECEPTIONIST,
            )
            .values(tts_ms=tts_ms, total_ms=total_ms)
        )

    async def count(
        self, clinic_id: uuid.UUID, conversation_id: uuid.UUID, speaker: Speaker
    ) -> int:
        stmt = select(func.count()).where(
            ConversationTurn.clinic_id == clinic_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.speaker == speaker,
        )
        return int(await self._session.scalar(stmt) or 0)
