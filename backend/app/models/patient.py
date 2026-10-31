# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Synthetic patient records, created or updated from a confirmed intake snapshot."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, func, text
from sqlalchemy import UniqueConstraint as Unique
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.contact import EMAIL_SQL_PATTERN, PHONE_SQL_PATTERN
from app.domain.enums import ContactChannel, PatientStatus, PatientType
from app.models.base import Base, Timestamps, UUIDPrimaryKey, enum_check, str_enum


class Patient(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "patients"
    __table_args__ = (
        Unique("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "persona_id"], ["synthetic_personas.clinic_id", "synthetic_personas.id"]
        ),
        CheckConstraint(f"email IS NULL OR email ~* '{EMAIL_SQL_PATTERN}'", name="email_reserved"),
        CheckConstraint(f"phone IS NULL OR phone ~ '{PHONE_SQL_PATTERN}'", name="phone_reserved"),
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="has_contact"),
        enum_check("patient_type", PatientType),
        enum_check("status", PatientStatus),
        enum_check("preferred_contact_channel", ContactChannel),
        # Duplicate detection backed by the database: one record per contact value per clinic.
        Index(
            "uq_patients_clinic_email",
            "clinic_id",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_patients_clinic_phone",
            "clinic_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index("ix_patients_clinic_last_name", "clinic_id", "last_name"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(16))
    preferred_contact_channel: Mapped[ContactChannel | None] = mapped_column(
        str_enum(ContactChannel, 8)
    )
    patient_type: Mapped[PatientType] = mapped_column(str_enum(PatientType, 16))
    status: Mapped[PatientStatus] = mapped_column(
        str_enum(PatientStatus, 16), server_default=PatientStatus.PROSPECTIVE.value
    )
