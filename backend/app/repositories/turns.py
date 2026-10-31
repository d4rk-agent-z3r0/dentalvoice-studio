# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
