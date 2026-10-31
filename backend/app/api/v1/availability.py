# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Availability endpoint. The clinic is always ``principal.clinic_id``, from the token."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentPrincipal, SessionFactory
from app.schemas.booking import AvailabilityRead
from app.services.booking.availability import MAX_DAYS, AvailabilityService

router = APIRouter(prefix="/availability", tags=["booking"])


@router.get("", response_model=AvailabilityRead)
async def get_availability(
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    appointment_type_id: uuid.UUID,
    first_day: Annotated[
        date, Query(alias="date", description="First clinic-local day (YYYY-MM-DD).")
    ],
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 1,
) -> AvailabilityRead:
    return await AvailabilityService(session_factory).find(
        principal.clinic_id, appointment_type_id, first_day, days
    )
