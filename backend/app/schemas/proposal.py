# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The contract between a conversation model (Gemini or the mock) and the orchestrator.

A model turn returns a ``TurnProposal``. It is a *proposal*: the orchestrator validates every
field update, decides the next state itself and may discard the response text (ADR-0003). There
are no tools and no way to name a state.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import IntakeField


class NextAction(StrEnum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    ASK_NEXT_FIELD = "ASK_NEXT_FIELD"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    CONFIRM = "CONFIRM"
    ESCALATE = "ESCALATE"
    END = "END"


class Intent(StrEnum):
    GREETING = "greeting"
    PROVIDE_INFORMATION = "provide_information"
    CORRECTION = "correction"
    CONFIRMATION = "confirmation"
    DENIAL = "denial"
    DECLINE = "decline"
    APPOINTMENT_PREFERENCE = "appointment_preference"
    UNCLEAR = "unclear"
    URGENT_SYMPTOMS = "urgent_symptoms"
    GOODBYE = "goodbye"
    OFF_TOPIC = "off_topic"


class FieldUpdates(BaseModel):
    """Proposed raw values. Every one is validated and normalised before it is stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_name: str | None = None
    last_name: str | None = None
    patient_type: str | None = None
    preferred_contact_channel: str | None = None
    email: str | None = None
    phone: str | None = None
    visit_reason: str | None = None
    requested_service: str | None = None
    preferred_date: str | None = Field(default=None, description="ISO date, YYYY-MM-DD")
    preferred_time: str | None = Field(default=None, description="24-hour time, HH:MM")

    def items(self) -> list[tuple[IntakeField, str]]:
        return [
            (IntakeField(name), value) for name, value in self.model_dump(exclude_none=True).items()
        ]


class TurnProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assistant_response: str = Field(min_length=1, max_length=600)
    intent: Intent
    field_updates: FieldUpdates = Field(default_factory=FieldUpdates)
    corrected_fields: list[IntakeField] = Field(default_factory=list)
    declined_fields: list[IntakeField] = Field(default_factory=list)
    missing_fields: list[IntakeField] = Field(default_factory=list)  # advisory only
    next_action: NextAction
    confidence: float = Field(ge=0.0, le=1.0)
    requires_escalation: bool = False
    escalation_reason: str | None = Field(default=None, max_length=120)
