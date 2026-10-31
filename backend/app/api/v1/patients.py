# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Patient records, read only. The clinic is always ``principal.clinic_id``, from the token."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentPrincipal, SessionFactory
from app.domain.enums import PatientStatus
from app.schemas.patient import PatientDetail, PatientRead
from app.services.patients import PatientService

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=list[PatientRead])
async def list_patients(
    principal: CurrentPrincipal,
    session_factory: SessionFactory,
    q: Annotated[
        str | None,
        Query(max_length=254, description="Case-insensitive match on name, full name or email."),
    ] = None,
    status: PatientStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[PatientRead]:
    """Ordered by last name, first name, then id, so pages are stable."""
    query = q.strip() if q else None
    return await PatientService(session_factory).list(
        principal.clinic_id, query=query or None, status=status, limit=limit, offset=offset
    )


@router.get("/{patient_id}", response_model=PatientDetail)
async def get_patient(
    patient_id: uuid.UUID, principal: CurrentPrincipal, session_factory: SessionFactory
) -> PatientDetail:
    return await PatientService(session_factory).detail(principal.clinic_id, patient_id)
