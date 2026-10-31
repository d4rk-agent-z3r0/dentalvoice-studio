# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ContactChannel, ConversationState, IntakeField, PatientType
from app.schemas.common import ReadModel


class ScenarioExpectation(BaseModel):
    """What a scenario must produce. Stored as ``synthetic_scenarios.expected`` (jsonb)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    states: list[ConversationState]
    final_state: ConversationState
    fields: dict[IntakeField, str]
    missing_fields: list[IntakeField] = []
    corrected_fields: list[IntakeField] = []
    escalation_reason: str | None = None


class PersonaRead(ReadModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    preferred_contact_channel: ContactChannel
    patient_type: PatientType
    background: str


class ScenarioRead(ReadModel):
    id: uuid.UUID
    code: str
    title: str
    objective: str
    clips: list[str]
    persona_id: uuid.UUID
