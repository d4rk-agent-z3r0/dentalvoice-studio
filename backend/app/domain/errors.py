# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Domain errors. The API layer maps each ``code`` to an HTTP status (docs/api-reference.md)."""


class DomainError(Exception):
    code = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ForbiddenError(DomainError):
    """Authenticated but not allowed: the role forbids it, or the clinic is not the caller's."""

    code = "FORBIDDEN"


class NotFoundError(DomainError):
    """Also raised for another clinic's resources, so existence never leaks across tenants."""

    code = "NOT_FOUND"

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found.")
        self.resource = resource


class DuplicatePatientError(DomainError):
    code = "DUPLICATE_PATIENT"

    def __init__(self) -> None:
        super().__init__("A patient with this contact value already exists in this clinic.")


class InvalidStateTransitionError(DomainError):
    code = "INVALID_STATE_TRANSITION"


class ConcurrentUpdateError(DomainError):
    code = "CONCURRENT_UPDATE"


class ConversationClosedError(DomainError):
    code = "CONVERSATION_CLOSED"

    def __init__(self) -> None:
        super().__init__("This conversation has ended.")


class ConversationNotStartedError(DomainError):
    code = "INVALID_STATE_TRANSITION"

    def __init__(self) -> None:
        super().__init__("Start the conversation before sending caller turns.")


class BookingSlotTakenError(DomainError):
    """Another active appointment holds an overlapping time (the database exclusion constraint)."""

    code = "BOOKING_SLOT_TAKEN"

    def __init__(self) -> None:
        super().__init__("That time is no longer available.")


class SlotUnavailableError(DomainError):
    """The time is not bookable at all: in the past, not published, blocked or dentist inactive."""

    code = "SLOT_UNAVAILABLE"


class IdempotencyConflictError(DomainError):
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self) -> None:
        super().__init__("This Idempotency-Key was already used with a different request.")


class AppointmentNotActiveError(DomainError):
    code = "APPOINTMENT_NOT_ACTIVE"

    def __init__(self) -> None:
        super().__init__("This appointment is no longer active.")
