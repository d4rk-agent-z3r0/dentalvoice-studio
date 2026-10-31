# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Appointments. Double booking is prevented by the database, not by application checks."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus
from app.models.base import Base, Timestamps, UUIDPrimaryKey, enum_check, str_enum

_ACTIVE = ", ".join(f"'{s.value}'" for s in sorted(ACTIVE_APPOINTMENT_STATUSES))


class Appointment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("clinic_id", "idempotency_key"),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "dentist_id"], ["dentists.clinic_id", "dentists.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_type_id"],
            ["appointment_types.clinic_id", "appointment_types.id"],
        ),
        ForeignKeyConstraint(
            ["clinic_id", "conversation_id"], ["conversations.clinic_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["clinic_id", "rescheduled_from_id"], ["appointments.clinic_id", "appointments.id"]
        ),
        enum_check("status", AppointmentStatus),
        CheckConstraint("starts_at < ends_at", name="start_before_end"),
        CheckConstraint("length(idempotency_key) BETWEEN 8 AND 128", name="idempotency_key_length"),
        ExcludeConstraint(
            ("dentist_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_appointments_dentist_no_overlap",
            using="gist",
            where=text(f"status IN ({_ACTIVE})"),
        ),
        Index("ix_appointments_clinic_starts_at", "clinic_id", "starts_at"),
        Index("ix_appointments_clinic_patient", "clinic_id", "patient_id"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    dentist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    appointment_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(str_enum(AppointmentStatus, 16))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex of the canonical request
