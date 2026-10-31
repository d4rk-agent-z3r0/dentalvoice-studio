# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Conversation endpoints. The clinic is always ``principal.clinic_id``, from the token."""

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    CurrentPrincipal,
    CurrentSettings,
    ForbiddenError,
    Operator,
    Orchestrator,
    SessionFactory,
)
from app.domain.enums import ConversationState
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    TextTurnCreate,
    TurnResultRead,
)
from app.services.conversations import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    principal: Operator,
    session_factory: SessionFactory,
    settings: CurrentSettings,
) -> ConversationRead:
    return await ConversationService(session_factory).create(
        principal.clinic_id,
        body.scenario_id,
        provider_mode=settings.voice_provider_mode,
        started_by_user_id=principal.user_id,
    )


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    state: ConversationState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationRead]:
    return await ConversationService(session_factory).list(
        principal.clinic_id, state=state, limit=limit
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, principal: CurrentPrincipal, session_factory: SessionFactory
) -> ConversationDetail:
    return await ConversationService(session_factory).detail(principal.clinic_id, conversation_id)


@router.post("/{conversation_id}/start", response_model=TurnResultRead)
async def start_conversation(
    conversation_id: uuid.UUID, principal: Operator, orchestrator: Orchestrator
) -> TurnResultRead:
    result = await orchestrator.start(principal.clinic_id, conversation_id)
    return TurnResultRead.model_validate(asdict(result))


@router.post("/{conversation_id}/turns", response_model=TurnResultRead)
async def create_text_turn(
    conversation_id: uuid.UUID,
    body: TextTurnCreate,
    principal: Operator,
    orchestrator: Orchestrator,
    settings: CurrentSettings,
) -> TurnResultRead:
    """Typed caller turn for development and automated tests. Disabled in production, where
    caller speech only ever comes from synthetic audio fixtures."""
    if not settings.text_turns_enabled:
        raise ForbiddenError("Typed turns are disabled in this environment.")
    result = await orchestrator.handle_caller_turn(principal.clinic_id, conversation_id, body.text)
    return TurnResultRead.model_validate(asdict(result))


@router.post("/{conversation_id}/end", response_model=ConversationRead)
async def end_conversation(
    conversation_id: uuid.UUID,
    principal: Operator,
    orchestrator: Orchestrator,
    session_factory: SessionFactory,
) -> ConversationRead:
    await orchestrator.end(principal.clinic_id, conversation_id)
    return await ConversationService(session_factory).get(principal.clinic_id, conversation_id)
