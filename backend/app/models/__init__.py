# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.booking import Appointment
from app.models.clinic import (
    AppointmentSlot,
    AppointmentType,
    Clinic,
    ClinicUser,
    Dentist,
    DentistSchedule,
    User,
)
from app.models.conversation import (
    Conversation,
    ConversationEvent,
    ConversationTurn,
    IntakeDraft,
    IntakeSnapshot,
)
from app.models.demo import SyntheticPersona, SyntheticScenario
from app.models.patient import Patient

__all__ = [
    "Appointment",
    "AppointmentSlot",
    "AppointmentType",
    "AuditEvent",
    "Base",
    "Clinic",
    "ClinicUser",
    "Conversation",
    "ConversationEvent",
    "ConversationTurn",
    "Dentist",
    "DentistSchedule",
    "IntakeDraft",
    "IntakeSnapshot",
    "Patient",
    "SyntheticPersona",
    "SyntheticScenario",
    "User",
]
