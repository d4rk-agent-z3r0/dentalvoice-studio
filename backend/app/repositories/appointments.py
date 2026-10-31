# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped appointment queries. Every method takes ``clinic_id``; none commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ACTIVE_APPOINTMENT_STATUSES
from app.models import Appointment


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active_overlapping(
        self, clinic_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[Appointment]:
        """Active (``requested``/``confirmed``) appointments overlapping ``[start, end)``."""
        stmt = select(Appointment).where(
            Appointment.clinic_id == clinic_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.starts_at < end,
            Appointment.ends_at > start,
        )
        return (await self._session.scalars(stmt)).all()
