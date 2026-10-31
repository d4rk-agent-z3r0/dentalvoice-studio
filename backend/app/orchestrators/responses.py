# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deterministic receptionist replies, derived from the state the application decided on.

Used whenever the provider does not write its own replies (the mock), and always for safety-
critical moments (escalation, completion, abandonment), where wording must never come from a
model.
"""

from dataclasses import dataclass
from datetime import date

from app.domain.enums import ContactChannel, ConversationState, IntakeField
from app.services.intake.stages import FIELD_STAGE

S = ConversationState
F = IntakeField

_ASKING = frozenset(
    {
        S.INTRODUCTION,
        S.IDENTITY_COLLECTION,
        S.CONTACT_DETAILS,
        S.VISIT_REASON,
        S.APPOINTMENT_PREFERENCES,
    }
)

ESCALATION_MESSAGE = (
    "I'm sorry you're going through that. Under this demo's urgent-symptom protocol I'm stopping "
    "the routine registration and flagging your call for immediate attention by the clinic team. "
    "If you have difficulty breathing or swallowing, please contact your local emergency "
    "services now."
)

_LABELS = {
    F.FIRST_NAME: "first name",
    F.LAST_NAME: "last name",
    F.PATIENT_TYPE: "patient type",
    F.PREFERRED_CONTACT_CHANNEL: "contact preference",
    F.EMAIL: "email address",
    F.PHONE: "phone number",
    F.VISIT_REASON: "reason for the visit",
    F.REQUESTED_SERVICE: "service",
    F.PREFERRED_DATE: "date",
    F.PREFERRED_TIME: "time",
}


@dataclass(frozen=True)
class ReplyContext:
    clinic_name: str
    state: ConversationState
    values: dict[IntakeField, str | None]
    missing: list[IntakeField]
    services: dict[str, str]
    rejected: dict[IntakeField, str]
    corrected: list[IntakeField]
    clarification: bool


def _date(value: str | None) -> str:
    if value is None:
        return "an unspecified day"
    day = date.fromisoformat(value)
    return f"{day:%A}, {day.day} {day:%B}"


def _ask_contact(ctx: ReplyContext) -> str:
    missing = set(ctx.missing)
    if F.PREFERRED_CONTACT_CHANNEL in missing and F.EMAIL in missing and F.PHONE in missing:
        return "How would you prefer we contact you, by email or by phone?"
    if F.PREFERRED_CONTACT_CHANNEL in missing:
        return "Would you prefer we contact you by email or by phone?"
    if F.EMAIL in missing:
        return "What's the best email address for you?"
    return "And what's a good phone number to reach you?"


def _summary(ctx: ReplyContext) -> str:
    v = ctx.values
    channel = v.get(F.PREFERRED_CONTACT_CHANNEL)
    contact = v.get(F.EMAIL) if channel == ContactChannel.EMAIL else v.get(F.PHONE)
    service = ctx.services.get(v.get(F.REQUESTED_SERVICE) or "", "an appointment")
    return (
        f"Let me read that back. {v.get(F.FIRST_NAME)} {v.get(F.LAST_NAME)}, "
        f"{v.get(F.PATIENT_TYPE)} patient. We'll contact you by {channel} at {contact}. "
        f"{service} for {v.get(F.VISIT_REASON)}, preferably on {_date(v.get(F.PREFERRED_DATE))} "
        f"at {v.get(F.PREFERRED_TIME)}. Is all of that correct?"
    )


def compose_reply(ctx: ReplyContext) -> str:
    prefix = ""
    if ctx.rejected:
        name, reason = next(iter(ctx.rejected.items()))
        prefix = f"Sorry, I couldn't use that {_LABELS[name]}. {reason} "
    elif ctx.corrected:
        prefix = f"Thanks, I've updated your {_LABELS[ctx.corrected[0]]}. "
    elif F.EMAIL in ctx.values and ctx.state is S.CONTACT_DETAILS and ctx.values[F.EMAIL]:
        prefix = f"I have {ctx.values[F.EMAIL]}. "

    # In collection stages ask about the earliest missing field, wherever it lives.
    topic = ctx.state
    if ctx.state in _ASKING and ctx.missing:
        topic = FIELD_STAGE[ctx.missing[0]]

    match topic:
        case S.GREETING:
            return (
                f"Hello! Welcome to {ctx.clinic_name}. I'm your virtual receptionist. I can help "
                "you with our demonstration patient registration and appointment process. "
                "How may I help you today?"
            )
        case S.INTRODUCTION:
            return prefix + "Happy to help. Are you a new patient, or have you visited us before?"
        case S.IDENTITY_COLLECTION:
            if F.FIRST_NAME in ctx.missing:
                return prefix + "Happy to help with that. Could I have your first and last name?"
            return prefix + f"Thanks, {ctx.values.get(F.FIRST_NAME)}. And your last name?"
        case S.CONTACT_DETAILS:
            return prefix + _ask_contact(ctx)
        case S.VISIT_REASON:
            if F.VISIT_REASON in ctx.missing:
                return prefix + "Thank you. What's the reason for your visit?"
            names = ", ".join(ctx.services.values())
            return prefix + f"Which service would you like? We offer: {names}."
        case S.APPOINTMENT_PREFERENCES:
            if ctx.clarification:
                return (
                    "No problem. If you have a day and time in mind, I can note it now, or you "
                    "can call back when you know."
                )
            if F.PREFERRED_DATE in ctx.missing and F.PREFERRED_TIME in ctx.missing:
                return prefix + "Do you have a preferred day and time for your appointment?"
            if F.PREFERRED_DATE in ctx.missing:
                return prefix + "Which day would you prefer?"
            return prefix + "And what time of day works best for you?"
        case S.INFORMATION_REVIEW:
            if ctx.clarification:
                return "Of course. What would you like to change?"
            return prefix + _summary(ctx)
        case S.CONFIRMATION_PENDING:
            return "Thank you. Shall I submit your registration and appointment request?"
        case S.COMPLETED:
            service = ctx.services.get(ctx.values.get(F.REQUESTED_SERVICE) or "", "appointment")
            return (
                f"All set. Your details are registered and your request for a {service.lower()} "
                f"on {_date(ctx.values.get(F.PREFERRED_DATE))} at "
                f"{ctx.values.get(F.PREFERRED_TIME)} has been recorded. The clinic will confirm "
                "the appointment time. Thank you for calling, goodbye!"
            )
        case S.ESCALATED:
            return ESCALATION_MESSAGE
        case S.ABANDONED:
            return "No problem at all. You're welcome to call back whenever you're ready. Goodbye!"
        case S.CREATED:
            raise ValueError("No reply exists for a conversation that has not started.")
