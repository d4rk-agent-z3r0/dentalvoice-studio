# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Clinic-scoped appointment queries. Every method takes ``clinic_id``; none commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus
from app.models import Appointment


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, appointment: Appointment) -> None:
        self._session.add(appointment)

    async def get(self, clinic_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment | None:
        stmt = select(Appointment).where(
            Appointment.clinic_id == clinic_id, Appointment.id == appointment_id
        )
        return await self._session.scalar(stmt)

    async def lock_dentist_calendar(self, clinic_id: uuid.UUID, dentist_id: uuid.UUID) -> None:
        """Hold a transaction-scoped lock on one dentist's calendar until commit or rollback.

        Two transactions inserting overlapping appointments can each find the other's
        uncommitted row through the exclusion constraint and wait for it: a deadlock. Taking
        this lock first makes bookings for one dentist queue instead; the constraint still
        decides who wins. Other dentists are not affected.
        """
        key = func.hashtextextended(f"appointments:{clinic_id}:{dentist_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def get_for_update(
        self, clinic_id: uuid.UUID, appointment_id: uuid.UUID
    ) -> Appointment | None:
        """Row-locked read: serialises cancel and reschedule of one appointment."""
        stmt = (
            select(Appointment)
            .where(Appointment.clinic_id == clinic_id, Appointment.id == appointment_id)
            .with_for_update()
        )
        return await self._session.scalar(stmt)

    async def get_by_idempotency_key(
        self, clinic_id: uuid.UUID, idempotency_key: str
    ) -> Appointment | None:
        stmt = select(Appointment).where(
            Appointment.clinic_id == clinic_id, Appointment.idempotency_key == idempotency_key
        )
        return await self._session.scalar(stmt)

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

    async def list_for_patient(
        self, clinic_id: uuid.UUID, patient_id: uuid.UUID, *, limit: int = 100
    ) -> Sequence[Appointment]:
        """A patient's appointments in every status, latest start first."""
        stmt = (
            select(Appointment)
            .where(Appointment.clinic_id == clinic_id, Appointment.patient_id == patient_id)
            .order_by(Appointment.starts_at.desc(), Appointment.id.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def list(
        self,
        clinic_id: uuid.UUID,
        *,
        starts_from: datetime | None = None,
        starts_before: datetime | None = None,
        status: AppointmentStatus | None = None,
        limit: int = 100,
    ) -> Sequence[Appointment]:
        stmt: Select[Appointment] = select(Appointment).where(Appointment.clinic_id == clinic_id)
        if starts_from is not None:
            stmt = stmt.where(Appointment.starts_at >= starts_from)
        if starts_before is not None:
            stmt = stmt.where(Appointment.starts_at < starts_before)
        if status is not None:
            stmt = stmt.where(Appointment.status == status)
        stmt = stmt.order_by(Appointment.starts_at, Appointment.id).limit(limit)
        return (await self._session.scalars(stmt)).all()
