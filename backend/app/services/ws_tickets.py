# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Single-use WebSocket admission tickets (ADR-0006).

Browsers cannot send an Authorization header on a WebSocket, and an access token in a URL can
end up in logs and history. So an authenticated REST call exchanges the access token for a
random ticket that is bound to one user, clinic and conversation, expires in seconds, and works
exactly once. Only its SHA-256 is stored.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import TERMINAL_STATES
from app.domain.errors import ConversationClosedError, NotFoundError
from app.models import WsTicket
from app.repositories.conversations import ConversationRepository

TICKET_TTL_SECONDS = 60


class TicketRejectedError(Exception):
    """Unknown, expired, already used, or issued for a different conversation."""


@dataclass(frozen=True)
class IssuedTicket:
    ticket: str
    expires_in: int


@dataclass(frozen=True)
class Admission:
    clinic_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("ascii", errors="replace")).hexdigest()


class TicketService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def issue(
        self, clinic_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> IssuedTicket:
        ticket = secrets.token_urlsafe(32)
        async with self._sf.begin() as session:
            conversation = await ConversationRepository(session).get(clinic_id, conversation_id)
            if conversation is None:
                raise NotFoundError("Conversation")
            if conversation.state in TERMINAL_STATES:
                raise ConversationClosedError
            now = datetime.now(UTC)
            session.add(
                WsTicket(
                    token_hash=_hash(ticket),
                    clinic_id=clinic_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + timedelta(seconds=TICKET_TTL_SECONDS),
                )
            )
        return IssuedTicket(ticket=ticket, expires_in=TICKET_TTL_SECONDS)

    async def redeem(self, ticket: str, conversation_id: uuid.UUID) -> Admission:
        """Consume the ticket atomically. Two connections racing with one ticket: one wins."""
        now = datetime.now(UTC)
        async with self._sf.begin() as session:
            row = (
                await session.execute(
                    update(WsTicket)
                    .where(
                        WsTicket.token_hash == _hash(ticket),
                        WsTicket.conversation_id == conversation_id,
                        WsTicket.used_at.is_(None),
                        WsTicket.expires_at > now,
                    )
                    .values(used_at=now)
                    .returning(WsTicket.clinic_id, WsTicket.user_id)
                )
            ).one_or_none()
        if row is None:
            raise TicketRejectedError
        return Admission(clinic_id=row[0], user_id=row[1], conversation_id=conversation_id)
