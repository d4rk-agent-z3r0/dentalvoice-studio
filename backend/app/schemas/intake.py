# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.enums import ContactChannel, IntakeField, IntakeFieldStatus, PatientType
from app.schemas.common import ReadModel


class IntakeDraftRead(ReadModel):
    id: uuid.UUID
    field: IntakeField
    value: str | None
    status: IntakeFieldStatus
    confidence: Decimal | None
    source_turn_id: uuid.UUID | None
    rejection_reason: str | None
    created_at: datetime


class IntakeSnapshotData(BaseModel):
    """The confirmed result of an onboarding call. Validated again before it is stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_name: str
    last_name: str
    patient_type: PatientType
    preferred_contact_channel: ContactChannel
    email: str | None
    phone: str | None
    visit_reason: str
    requested_service: str
    preferred_date: date
    preferred_time: time
    provenance: dict[IntakeField, uuid.UUID]  # field -> the confirmed draft it came from

    @model_validator(mode="after")
    def _preferred_channel_has_a_value(self) -> Self:
        if self.preferred_contact_channel is ContactChannel.EMAIL and self.email is None:
            raise ValueError("Preferred channel is email but no email was confirmed.")
        if self.preferred_contact_channel is ContactChannel.PHONE and self.phone is None:
            raise ValueError("Preferred channel is phone but no phone was confirmed.")
        return self
