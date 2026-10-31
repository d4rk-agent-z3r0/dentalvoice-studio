# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped reads of the published calendar (``appointment_slots``). None commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import SlotStatus
from app.models import AppointmentSlot, Dentist


class SlotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open_starting_between(
        self, clinic_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[AppointmentSlot]:
        """Open slots of active dentists whose start lies in ``[start, end)``."""
        stmt = (
            select(AppointmentSlot)
            .join(
                Dentist,
                (Dentist.clinic_id == AppointmentSlot.clinic_id)
                & (Dentist.id == AppointmentSlot.dentist_id),
            )
            .where(
                AppointmentSlot.clinic_id == clinic_id,
                AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.starts_at >= start,
                AppointmentSlot.starts_at < end,
                Dentist.is_active.is_(True),
            )
            .order_by(AppointmentSlot.dentist_id, AppointmentSlot.starts_at)
        )
        return (await self._session.scalars(stmt)).all()

    async def overlapping_for_share(
        self, clinic_id: uuid.UUID, dentist_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[AppointmentSlot]:
        """Every slot (open or blocked) of one dentist overlapping ``[start, end)``.

        ``FOR SHARE`` keeps the rows from being blocked or removed by a concurrent writer until this
        transaction ends, so a booking cannot commit against a slot withdrawn mid-flight. Shared
        locks do not conflict with each other, so concurrent bookings are not serialised here.
        """
        stmt = (
            select(AppointmentSlot)
            .where(
                AppointmentSlot.clinic_id == clinic_id,
                AppointmentSlot.dentist_id == dentist_id,
                AppointmentSlot.starts_at < end,
                AppointmentSlot.ends_at > start,
            )
            .order_by(AppointmentSlot.starts_at)
            .with_for_update(read=True)
        )
        return (await self._session.scalars(stmt)).all()
