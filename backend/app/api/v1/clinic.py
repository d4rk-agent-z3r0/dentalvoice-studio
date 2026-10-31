# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The token's clinic. There is no clinic id in the path: the token names the clinic."""

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, SessionFactory
from app.schemas.clinic import ClinicRead
from app.services.clinics import ClinicService

router = APIRouter(prefix="/clinic", tags=["clinic"])


@router.get("", response_model=ClinicRead)
async def get_clinic(principal: CurrentPrincipal, session_factory: SessionFactory) -> ClinicRead:
    """Name, timezone, today's clinic-local date, appointment types and dentists."""
    return await ClinicService(session_factory).get(principal.clinic_id)
