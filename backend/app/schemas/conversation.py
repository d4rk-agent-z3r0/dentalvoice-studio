# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import ProviderMode
from app.domain.enums import ConversationState, IntakeField, Speaker
from app.schemas.common import ReadModel, WriteModel
from app.schemas.intake import IntakeDraftRead, IntakeSnapshotData


class ConversationRead(ReadModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    patient_id: uuid.UUID | None
    state: ConversationState
    state_version: int
    provider_mode: ProviderMode
    turn_count: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class ConversationCreate(WriteModel):
    scenario_id: uuid.UUID


class TextTurnCreate(WriteModel):
    """Development and test only: a typed caller utterance in place of a synthetic audio clip."""

    text: str = Field(min_length=1, max_length=500)


class TurnRead(ReadModel):
    seq: int
    speaker: Speaker
    text: str
    clip_id: str | None
    stt_ms: int | None
    llm_ms: int | None
    tts_ms: int | None
    total_ms: int | None
    created_at: datetime


class EventRead(ReadModel):
    type: str
    payload: dict[str, Any]
    created_at: datetime


class TurnResultRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    previous_state: ConversationState
    state: ConversationState
    path: list[ConversationState]
    state_version: int
    reply: str
    receptionist_turn_seq: int
    caller_turn_seq: int | None
    missing_fields: list[IntakeField]
    rejected_fields: dict[IntakeField, str]
    corrected_fields: list[IntakeField]
    llm_ms: int | None


class ConversationDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation: ConversationRead
    turns: list[TurnRead]
    events: list[EventRead]
    intake: list[IntakeDraftRead]
    missing_fields: list[IntakeField]
    snapshot: IntakeSnapshotData | None
