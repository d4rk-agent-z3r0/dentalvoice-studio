# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Domain vocabularies. Stored as text with CHECK constraints (see docs/database-design.md)."""

from enum import StrEnum


class ClinicRole(StrEnum):
    ADMIN = "admin"
    STAFF = "staff"
    VIEWER = "viewer"


class ConversationState(StrEnum):
    CREATED = "CREATED"
    GREETING = "GREETING"
    INTRODUCTION = "INTRODUCTION"
    IDENTITY_COLLECTION = "IDENTITY_COLLECTION"
    CONTACT_DETAILS = "CONTACT_DETAILS"
    VISIT_REASON = "VISIT_REASON"
    APPOINTMENT_PREFERENCES = "APPOINTMENT_PREFERENCES"
    INFORMATION_REVIEW = "INFORMATION_REVIEW"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"


TERMINAL_STATES = frozenset(
    {ConversationState.COMPLETED, ConversationState.ESCALATED, ConversationState.ABANDONED}
)


class Speaker(StrEnum):
    CALLER = "caller"
    RECEPTIONIST = "receptionist"


class IntakeField(StrEnum):
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    PATIENT_TYPE = "patient_type"
    PREFERRED_CONTACT_CHANNEL = "preferred_contact_channel"
    EMAIL = "email"
    PHONE = "phone"
    VISIT_REASON = "visit_reason"
    REQUESTED_SERVICE = "requested_service"
    PREFERRED_DATE = "preferred_date"
    PREFERRED_TIME = "preferred_time"


class IntakeFieldStatus(StrEnum):
    """Extraction outcomes. The spec's four categories map to: provided / confirmed (explicitly
    provided), not_provided (caller declined; a field never mentioned has no row at all),
    needs_confirmation, and rejected. Superseded rows keep the history of corrections."""

    PROVIDED = "provided"
    NOT_PROVIDED = "not_provided"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


LIVE_INTAKE_STATUSES = frozenset(
    {
        IntakeFieldStatus.PROVIDED,
        IntakeFieldStatus.NOT_PROVIDED,
        IntakeFieldStatus.NEEDS_CONFIRMATION,
        IntakeFieldStatus.CONFIRMED,
    }
)


class PatientType(StrEnum):
    NEW = "new"
    RETURNING = "returning"


class ContactChannel(StrEnum):
    EMAIL = "email"
    PHONE = "phone"


class PatientStatus(StrEnum):
    PROSPECTIVE = "prospective"
    REGISTERED = "registered"
    ARCHIVED = "archived"


class SlotStatus(StrEnum):
    OPEN = "open"
    BLOCKED = "blocked"


class AppointmentStatus(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


ACTIVE_APPOINTMENT_STATUSES = frozenset({AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED})
