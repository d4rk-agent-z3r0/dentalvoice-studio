# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Appointment endpoints. The clinic is always ``principal.clinic_id``, from the token.

A ``201`` from a write means the transaction has committed; any failure is an error response, never
a provisional success.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from fastapi.exceptions import RequestValidationError

from app.api.deps import CurrentPrincipal, Operator, SessionFactory
from app.domain.enums import AppointmentStatus
from app.schemas.booking import AppointmentCreate, AppointmentRead, AppointmentReschedule
from app.services.booking.idempotency import CLIENT_KEY_PATTERN
from app.services.booking.reservations import ReservationService

router = APIRouter(prefix="/appointments", tags=["booking"])

REPLAY_HEADER = "Idempotent-Replayed"

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=CLIENT_KEY_PATTERN,
        description="8-128 characters from A-Z a-z 0-9 _ -; one key per intended booking.",
    ),
]


@router.get("", response_model=list[AppointmentRead])
async def list_appointments(
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    first_day: Annotated[date | None, Query(alias="from")] = None,
    last_day: Annotated[date | None, Query(alias="to")] = None,
    status: AppointmentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AppointmentRead]:
    if first_day is not None and last_day is not None and first_day > last_day:
        raise RequestValidationError(
            [{"loc": ("query", "to"), "msg": "'to' must not be before 'from'.", "type": "value"}]
        )
    return await ReservationService(session_factory).list(
        principal.clinic_id, first_day=first_day, last_day=last_day, status=status, limit=limit
    )


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentCreate,
    principal: Operator,
    session_factory: SessionFactory,
    idempotency_key: IdempotencyKey,
    response: Response,
) -> AppointmentRead:
    """Book and confirm. Replaying the same key with the same body returns the original
    appointment (same status code, ``Idempotent-Replayed: true``); a different body is a 409."""
    reservation = await ReservationService(session_factory).reserve(
        principal.clinic_id, body, idempotency_key
    )
    if reservation.replayed:
        response.headers[REPLAY_HEADER] = "true"
    return reservation.appointment


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
async def cancel_appointment(
    appointment_id: uuid.UUID, principal: Operator, session_factory: SessionFactory
) -> AppointmentRead:
    return await ReservationService(session_factory).cancel(principal.clinic_id, appointment_id)


@router.post(
    "/{appointment_id}/reschedule",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    body: AppointmentReschedule,
    principal: Operator,
    session_factory: SessionFactory,
) -> AppointmentRead:
    """Returns the new appointment; the original becomes ``rescheduled`` in the same transaction."""
    return await ReservationService(session_factory).reschedule(
        principal.clinic_id, appointment_id, body.starts_at
    )
