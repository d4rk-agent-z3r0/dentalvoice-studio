# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Voice transport: ticket issue (REST) and the conversation WebSocket.

The socket is admitted only with a single-use ticket bound to this conversation (ADR-0006),
checked before the handshake is accepted. Clients send small JSON commands only; binary frames
(audio) from the client are refused, because caller audio comes exclusively from the server's
synthetic fixtures (ADR-0002).
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel, ConfigDict
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.deps import Operator, SessionFactory
from app.core.logging import get_logger
from app.orchestrators.voice_session import VoiceSession
from app.services.conversations import ConversationService
from app.services.ws_tickets import TicketRejectedError, TicketService

log = get_logger(__name__)
router = APIRouter(tags=["voice"])

MAX_COMMAND_BYTES = 1024
# Close codes in the application range (4000-4999).
CLOSE_TICKET_REJECTED = 4401


class TicketRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket: str
    expires_in: int


@router.post("/conversations/{conversation_id}/ws-ticket", response_model=TicketRead)
async def issue_ticket(
    conversation_id: uuid.UUID, principal: Operator, session_factory: SessionFactory
) -> TicketRead:
    issued = await TicketService(session_factory).issue(
        principal.clinic_id, principal.user_id, conversation_id
    )
    return TicketRead(ticket=issued.ticket, expires_in=issued.expires_in)


class _SocketOutbound:
    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(data, separators=(",", ":")))

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)


async def _commands(websocket: WebSocket, out: _SocketOutbound) -> AsyncIterator[dict[str, Any]]:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            await out.send_json(
                {
                    "type": "error",
                    "code": "AUDIO_NOT_ACCEPTED",
                    "message": "Caller audio comes only from the scenario's synthetic clips.",
                }
            )
            continue
        text = message.get("text") or ""
        try:
            if len(text.encode()) > MAX_COMMAND_BYTES:
                raise ValueError("too large")
            command = json.loads(text)
            if not isinstance(command, dict):
                raise ValueError("not an object")
        except ValueError:
            await out.send_json(
                {"type": "error", "code": "INVALID_MESSAGE", "message": "Malformed command."}
            )
            continue
        yield command


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(
    websocket: WebSocket,
    conversation_id: uuid.UUID,
    ticket: Annotated[str, Query(min_length=20, max_length=128)],
) -> None:
    app_state = websocket.app.state
    try:
        admission = await TicketService(app_state.session_factory).redeem(ticket, conversation_id)
    except TicketRejectedError:
        log.info("ws_ticket_rejected", conversation_id=str(conversation_id))
        await websocket.close(code=CLOSE_TICKET_REJECTED)
        return

    await websocket.accept()
    out = _SocketOutbound(websocket)
    session = VoiceSession(
        clinic_id=admission.clinic_id,
        conversation_id=conversation_id,
        orchestrator=app_state.orchestrator,
        conversations=ConversationService(app_state.session_factory),
        stt=app_state.speech.stt,
        tts=app_state.speech.tts,
        library=app_state.clip_library,
        out=out,
        realtime_factor=app_state.settings.voice_realtime_factor,
    )
    log.info("ws_session_started", conversation_id=str(conversation_id))
    try:
        await session.run(_commands(websocket, out))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close(code=1000)
        log.info("ws_session_ended", conversation_id=str(conversation_id), closed=session.closed)
