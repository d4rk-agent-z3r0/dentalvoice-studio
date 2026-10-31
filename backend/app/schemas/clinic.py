# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The token's clinic and its booking reference data."""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.schemas.common import ReadModel


class AppointmentTypeRead(ReadModel):
    id: uuid.UUID
    code: str
    name: str
    duration_minutes: int
    is_active: bool


class DentistRead(ReadModel):
    id: uuid.UUID
    display_name: str
    is_active: bool


class ClinicRead(BaseModel):
    """``today`` is the current calendar day in the clinic's timezone, the natural first day for
    availability and appointment lists. Inactive types and dentists are included so existing
    appointments can still be described; only active ones can be booked."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    timezone: str
    today: date
    appointment_types: list[AppointmentTypeRead]
    dentists: list[DentistRead]
