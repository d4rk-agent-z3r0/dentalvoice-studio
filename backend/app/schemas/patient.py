# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import date, datetime, time
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.config import ProviderMode
from app.domain.enums import ContactChannel, ConversationState, PatientStatus, PatientType
from app.schemas.booking import AppointmentRead
from app.schemas.common import PersonName, ReadModel, ReservedEmail, ReservedPhone, WriteModel


class PatientCreate(WriteModel):
    first_name: PersonName
    last_name: PersonName
    email: ReservedEmail | None = None
    phone: ReservedPhone | None = None
    preferred_contact_channel: ContactChannel | None = None
    patient_type: PatientType
    persona_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _contact_is_consistent(self) -> Self:
        if self.email is None and self.phone is None:
            raise ValueError("At least one contact value (email or phone) is required.")
        channel = self.preferred_contact_channel
        if channel is ContactChannel.EMAIL and self.email is None:
            raise ValueError("Preferred channel is email but no email was given.")
        if channel is ContactChannel.PHONE and self.phone is None:
            raise ValueError("Preferred channel is phone but no phone was given.")
        return self


class PatientUpdate(WriteModel):
    """Partial update: only fields explicitly sent are changed (``model_fields_set``)."""

    first_name: PersonName | None = None
    last_name: PersonName | None = None
    email: ReservedEmail | None = None
    phone: ReservedPhone | None = None
    preferred_contact_channel: ContactChannel | None = None
    status: PatientStatus | None = None


class PatientRead(ReadModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    preferred_contact_channel: ContactChannel | None
    patient_type: PatientType
    status: PatientStatus
    created_at: datetime
    updated_at: datetime


class PatientConversationRead(BaseModel):
    """A conversation linked to the patient. ``snapshot_confirmed_at`` is set when the call ended
    with a confirmed intake snapshot."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    scenario_id: uuid.UUID
    state: ConversationState
    provider_mode: ProviderMode
    turn_count: int
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    snapshot_confirmed_at: datetime | None


class PatientSnapshotSummary(BaseModel):
    """What the most recently confirmed intake recorded about the visit. Contact values are on
    the patient record itself."""

    model_config = ConfigDict(frozen=True)

    conversation_id: uuid.UUID
    confirmed_at: datetime
    patient_type: PatientType
    preferred_contact_channel: ContactChannel
    visit_reason: str
    requested_service: str
    preferred_date: date
    preferred_time: time


class PatientDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    patient: PatientRead
    conversations: list[PatientConversationRead]
    appointments: list[AppointmentRead]
    latest_snapshot: PatientSnapshotSummary | None
