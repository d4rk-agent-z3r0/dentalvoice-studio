# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import uuid
from datetime import datetime
from typing import Self

from pydantic import model_validator

from app.domain.enums import ContactChannel, PatientStatus, PatientType
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
