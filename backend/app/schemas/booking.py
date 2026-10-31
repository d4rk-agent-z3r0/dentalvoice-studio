# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Booking DTOs. Instants are UTC (``…Z``); ``*_local`` fields are the same instants rendered in the
clinic's timezone with their UTC offset, for display only."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


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
