# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Tenants, identities, providers and the bookable calendar."""

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.contact import EMAIL_SQL_PATTERN
from app.domain.enums import ClinicRole, SlotStatus
from app.models.base import Base, Timestamps, UUIDPrimaryKey, enum_check, str_enum


class Clinic(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "clinics"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("length(name) BETWEEN 1 AND 120", name="name_length"),
    )

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    timezone: Mapped[str] = mapped_column(String(64))  # IANA name, validated by the service layer


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"email ~* '{EMAIL_SQL_PATTERN}'", name="email_reserved"),)

    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(Text)  # argon2id; set in Milestone 8
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ClinicUser(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "clinic_users"
    __table_args__ = (
        UniqueConstraint("clinic_id", "user_id"),
        enum_check("role", ClinicRole),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ClinicRole] = mapped_column(str_enum(ClinicRole, 16))


class Dentist(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "dentists"
    __table_args__ = (UniqueConstraint("clinic_id", "id"),)

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DentistSchedule(UUIDPrimaryKey, Timestamps, Base):
    """Recurring weekly working hours in the clinic's local time."""

    __tablename__ = "dentist_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "dentist_id"], ["dentists.clinic_id", "dentists.id"], ondelete="CASCADE"
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_local < end_local", name="start_before_end"),
        Index("ix_dentist_schedules_clinic_dentist", "clinic_id", "dentist_id"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    dentist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday, matching date.weekday()
    start_local: Mapped[time] = mapped_column(Time)
    end_local: Mapped[time] = mapped_column(Time)


class AppointmentType(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "appointment_types"
    __table_args__ = (
        UniqueConstraint("clinic_id", "code"),
        UniqueConstraint("clinic_id", "id"),
        CheckConstraint("duration_minutes > 0 AND duration_minutes % 15 = 0", name="duration"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_format"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class AppointmentSlot(UUIDPrimaryKey, Timestamps, Base):
    """A published, bookable block of a dentist's time (UTC).

    Slots are generated from ``dentist_schedules`` for a rolling horizon. They are the calendar
    that availability is read from; the exclusion constraint on ``appointments`` remains the final
    arbiter of double booking (ADR-0004).
    """

    __tablename__ = "appointment_slots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "dentist_id"], ["dentists.clinic_id", "dentists.id"], ondelete="CASCADE"
        ),
        CheckConstraint("starts_at < ends_at", name="start_before_end"),
        enum_check("status", SlotStatus),
        ExcludeConstraint(
            ("dentist_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_appointment_slots_dentist_no_overlap",
            using="gist",
        ),
        Index("ix_appointment_slots_clinic_starts_at", "clinic_id", "starts_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    dentist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SlotStatus] = mapped_column(
        str_enum(SlotStatus, 16), server_default=SlotStatus.OPEN.value
    )
