# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Simulated calls, their turns, timeline events and intake extraction records.

Every child row carries ``clinic_id`` and references its parent through ``(clinic_id, id)``, so the
database itself rejects a row that would link two clinics' data.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import ProviderMode
from app.domain.enums import (
    LIVE_INTAKE_STATUSES,
    TERMINAL_STATES,
    ConversationState,
    IntakeField,
    IntakeFieldStatus,
    Speaker,
)
from app.models.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey, enum_check, str_enum

_TERMINAL = ", ".join(f"'{s.value}'" for s in sorted(TERMINAL_STATES))
_LIVE = ", ".join(f"'{s.value}'" for s in sorted(LIVE_INTAKE_STATUSES))


def _conversation_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["clinic_id", "conversation_id"],
        ["conversations.clinic_id", "conversations.id"],
        ondelete="CASCADE",
    )


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "scenario_id"],
            ["synthetic_scenarios.clinic_id", "synthetic_scenarios.id"],
        ),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        enum_check("state", ConversationState),
        enum_check("provider_mode", ProviderMode),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint("turn_count >= 0", name="turn_count_non_negative"),
        CheckConstraint(
            f"(state IN ({_TERMINAL})) = (ended_at IS NOT NULL)", name="ended_iff_terminal"
        ),
        Index("ix_conversations_clinic_created_at", "clinic_id", "created_at"),
        Index("ix_conversations_clinic_state", "clinic_id", "state"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    state: Mapped[ConversationState] = mapped_column(
        str_enum(ConversationState, 32), server_default=ConversationState.CREATED.value
    )
    # Optimistic lock: every state change increments it, guarded by WHERE state_version = :seen.
    state_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    provider_mode: Mapped[ProviderMode] = mapped_column(str_enum(ProviderMode, 8))
    turn_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationTurn(UUIDPrimaryKey, CreatedAt, Base):
    """A committed utterance. Interim transcripts are never stored."""

    __tablename__ = "conversation_turns"
    __table_args__ = (
        _conversation_fk(),
        UniqueConstraint("conversation_id", "seq"),
        UniqueConstraint("clinic_id", "id"),
        enum_check("speaker", Speaker),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint(
            "coalesce(stt_ms, 0) >= 0 AND coalesce(llm_ms, 0) >= 0 "
            "AND coalesce(tts_ms, 0) >= 0 AND coalesce(total_ms, 0) >= 0",
            name="latency_non_negative",
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[Speaker] = mapped_column(str_enum(Speaker, 16))
    text: Mapped[str] = mapped_column(Text)
    clip_id: Mapped[str | None] = mapped_column(String(64))
    stt_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ms: Mapped[int | None] = mapped_column(Integer)
    tts_ms: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[int | None] = mapped_column(Integer)


class ConversationEvent(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only timeline: state changes, field decisions, provider errors, escalations."""

    __tablename__ = "conversation_events"
    __table_args__ = (
        _conversation_fk(),
        CheckConstraint("type ~ '^[a-z][a-z_.]*$'", name="type_format"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index("ix_conversation_events_conversation_created", "conversation_id", "created_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class IntakeDraft(UUIDPrimaryKey, Timestamps, Base):
    """One proposal for one field, with provenance. History is kept: corrections supersede."""

    __tablename__ = "intake_drafts"
    __table_args__ = (
        _conversation_fk(),
        ForeignKeyConstraint(
            ["clinic_id", "source_turn_id"],
            ["conversation_turns.clinic_id", "conversation_turns.id"],
        ),
        enum_check("field", IntakeField),
        enum_check("status", IntakeFieldStatus),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "(status = 'rejected') = (rejection_reason IS NOT NULL)", name="rejection_has_reason"
        ),
        CheckConstraint("(status = 'not_provided') = (value IS NULL)", name="value_presence"),
        # At most one live value per field; rejected and superseded rows are history.
        Index(
            "uq_intake_drafts_live_field",
            "conversation_id",
            "field",
            unique=True,
            postgresql_where=text(f"status IN ({_LIVE})"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    field: Mapped[IntakeField] = mapped_column(str_enum(IntakeField, 32))
    value: Mapped[str | None] = mapped_column(Text)
    status: Mapped[IntakeFieldStatus] = mapped_column(str_enum(IntakeFieldStatus, 24))
    source_turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rejection_reason: Mapped[str | None] = mapped_column(String(200))


class IntakeSnapshot(UUIDPrimaryKey, CreatedAt, Base):
    """The immutable, confirmed result of an onboarding call. Separate from the drafts."""

    __tablename__ = "intake_snapshots"
    __table_args__ = (
        _conversation_fk(),
        UniqueConstraint("conversation_id"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="data_is_object"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
