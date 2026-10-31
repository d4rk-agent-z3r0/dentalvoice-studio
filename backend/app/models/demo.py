# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Synthetic callers and the scripted scenarios they play."""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, Text
from sqlalchemy import UniqueConstraint as Unique
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.contact import EMAIL_SQL_PATTERN, PHONE_SQL_PATTERN
from app.domain.enums import ContactChannel, PatientType
from app.models.base import Base, Timestamps, UUIDPrimaryKey, enum_check, str_enum


class SyntheticPersona(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "synthetic_personas"
    __table_args__ = (
        Unique("clinic_id", "id"),
        CheckConstraint(f"email IS NULL OR email ~* '{EMAIL_SQL_PATTERN}'", name="email_reserved"),
        CheckConstraint(f"phone IS NULL OR phone ~ '{PHONE_SQL_PATTERN}'", name="phone_reserved"),
        enum_check("patient_type", PatientType),
        enum_check("preferred_contact_channel", ContactChannel),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clinics.id", ondelete="CASCADE")
    )
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(16))
    preferred_contact_channel: Mapped[ContactChannel] = mapped_column(str_enum(ContactChannel, 8))
    patient_type: Mapped[PatientType] = mapped_column(str_enum(PatientType, 16))
    background: Mapped[str] = mapped_column(Text)


class SyntheticScenario(UUIDPrimaryKey, Timestamps, Base):
    """A scripted call: which persona speaks, in which clip order, and what must come out of it."""

    __tablename__ = "synthetic_scenarios"
    __table_args__ = (
        Unique("clinic_id", "code"),
        Unique("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "persona_id"],
            ["synthetic_personas.clinic_id", "synthetic_personas.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("code ~ '^[A-Z]$'", name="code_format"),
        CheckConstraint("jsonb_typeof(clips) = 'array'", name="clips_is_array"),
        CheckConstraint("jsonb_typeof(expected) = 'object'", name="expected_is_object"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(String(1))
    title: Mapped[str] = mapped_column(String(120))
    objective: Mapped[str] = mapped_column(Text)
    clips: Mapped[list[str]] = mapped_column(JSONB)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB)
