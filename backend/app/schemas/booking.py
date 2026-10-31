# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Booking DTOs. Instants are UTC (``…Z``); ``*_local`` fields are the same instants rendered in the
clinic's timezone with their UTC offset, for display only."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict

from app.domain.enums import AppointmentStatus
from app.schemas.common import WriteModel


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# An instant with an explicit offset (a naive time is rejected), normalised to UTC, so the same
# instant written with different offsets is the same request.
UtcInstant = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class AppointmentCreate(WriteModel):
    patient_id: uuid.UUID
    appointment_type_id: uuid.UUID
    dentist_id: uuid.UUID
    starts_at: UtcInstant
    conversation_id: uuid.UUID | None = None


class AppointmentReschedule(WriteModel):
    starts_at: UtcInstant


class AppointmentRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    dentist_id: uuid.UUID
    appointment_type_id: uuid.UUID
    conversation_id: uuid.UUID | None
    rescheduled_from_id: uuid.UUID | None
    status: AppointmentStatus
    starts_at: datetime
    ends_at: datetime
    starts_at_local: str
    ends_at_local: str
    timezone: str
    created_at: datetime
    updated_at: datetime


class AvailableSlotRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    dentist_id: uuid.UUID
    dentist_name: str
    starts_at: datetime
    ends_at: datetime
    starts_at_local: str
    ends_at_local: str


class AvailabilityRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    appointment_type_id: uuid.UUID
    duration_minutes: int
    timezone: str
    first_day: date
    days: int
    slots: list[AvailableSlotRead]
