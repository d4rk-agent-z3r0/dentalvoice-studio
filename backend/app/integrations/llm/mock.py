# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deterministic, rule-based stand-in for the conversation model.

It reads the caller's utterance in the context of the current stage and returns the same
``TurnProposal`` contract the live model does, so the orchestrator, intake validation and state
machine are exercised identically. It recognises the phrasing used by the synthetic scenario
scripts and similar plain speech. It is not a language model and makes no attempt to be one.
"""

import re

from app.domain.enums import ConversationState, IntakeField
from app.domain.spoken import find_email, find_phone, find_time, find_weekday_date
from app.integrations.llm.base import ProposalResult, TurnContext
from app.schemas.proposal import FieldUpdates, Intent, NextAction, TurnProposal

S = ConversationState
F = IntakeField

# Demo protocol: phrases that end routine intake and escalate. Not a clinical assessment.
_URGENT = re.compile(
    r"swollen|swelling|hard to swallow|can'?t swallow|trouble breathing|can'?t breathe|"
    r"won'?t stop bleeding|knocked out|severe pain"
)
_NEW = re.compile(r"new patient|i'?m new|haven'?t been before|first time|never been")
_RETURNING = re.compile(r"existing patient|returning|i'?m a patient (?:there|with you)|been before")
_GOODBYE = re.compile(r"\bbye\b|call back|another time|hang up")
_AFFIRM = re.compile(r"\b(yes|yeah|yep|correct|right|confirm|go ahead|book it|sounds good)\b")
_DENY = re.compile(r"\b(no|nope|wrong|not right|incorrect)\b")
_CORRECTION = re.compile(r"\b(actually|sorry|instead|misspelled|mistake|change that)\b")
_UNSURE = re.compile(r"not sure|don'?t know|no idea|have to look|i'?ll check")
_NAME_PREFIX = re.compile(
    r"^(?:sure[.,!]?\s*)?(?:my name is|my name'?s|it'?s|i'?m|this is)\s+", re.I
)
_NAME_TOKEN = re.compile(r"[^\W\d_]+(?:['\-][^\W\d_]+)*")

# Service and visit-reason phrases used by the synthetic scripts, most specific first.
_SERVICES = (
    ("follow_up", re.compile(r"follow[- ]?up")),
    ("hygiene_cleaning", re.compile(r"cleaning")),
    ("checkup", re.compile(r"check[- ]?up|see a dentist")),
)
_REASONS = (
    ("routine cleaning", re.compile(r"routine cleaning")),
    ("check on a filling", re.compile(r"filling")),
    ("regular check-up", re.compile(r"regular check[- ]?up")),
    ("check-up", re.compile(r"check[- ]?up")),
    ("cleaning", re.compile(r"cleaning")),
)


def _first(table: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> str | None:
    return next((value for value, pattern in table if pattern.search(text)), None)


def _name(utterance: str) -> tuple[str | None, str | None]:
    stripped = _NAME_PREFIX.sub("", utterance.strip())
    tokens = _NAME_TOKEN.findall(stripped)
    if not tokens or len(tokens) > 4:
        return None, None
    return tokens[0], (" ".join(tokens[1:]) or None)


class MockConversationProvider:
    name = "mock"
    writes_responses = False

    async def propose(self, context: TurnContext) -> ProposalResult:
        return ProposalResult(self._propose(context))

    def _propose(self, context: TurnContext) -> TurnProposal:
        text = context.utterance.lower()
        updates: dict[str, str] = {}
        corrected: list[IntakeField] = []
        declined: list[IntakeField] = []

        if _URGENT.search(text):
            if _RETURNING.search(text):
                updates[F.PATIENT_TYPE] = "returning"
            return self._proposal(
                Intent.URGENT_SYMPTOMS,
                NextAction.ESCALATE,
                updates,
                escalate=True,
            )
        if _GOODBYE.search(text):
            return self._proposal(Intent.GOODBYE, NextAction.END, updates)

        state = context.state
        if state in (S.GREETING, S.INTRODUCTION):
            if _NEW.search(text):
                updates[F.PATIENT_TYPE] = "new"
            elif _RETURNING.search(text):
                updates[F.PATIENT_TYPE] = "returning"
            self._service(text, context, updates)
        elif state is S.IDENTITY_COLLECTION:
            first, last = _name(context.utterance)
            if first:
                key = F.LAST_NAME if F.FIRST_NAME in context.known_values and not last else None
                if key:
                    updates[key] = first
                else:
                    updates[F.FIRST_NAME] = first
                    if last:
                        updates[F.LAST_NAME] = last
        elif state is S.CONTACT_DETAILS:
            self._contact(text, context, updates, corrected, declined)
        elif state is S.VISIT_REASON:
            reason = _first(_REASONS, text)
            if reason:
                updates[F.VISIT_REASON] = reason
            self._service(text, context, updates)
        elif state is S.APPOINTMENT_PREFERENCES:
            self._preferences(text, context, updates)
            if not updates and _UNSURE.search(text):
                return self._proposal(Intent.UNCLEAR, NextAction.ASK_CLARIFICATION, updates)
        elif state in (S.INFORMATION_REVIEW, S.CONFIRMATION_PENDING):
            if _CORRECTION.search(text) or (_DENY.search(text) and not _AFFIRM.search(text)):
                self._preferences(text, context, updates)
                self._contact(text, context, updates, corrected, declined)
                corrected = [IntakeField(k) for k in updates]
                if updates:
                    return self._proposal(
                        Intent.CORRECTION, NextAction.ASK_NEXT_FIELD, updates, corrected=corrected
                    )
                return self._proposal(Intent.DENIAL, NextAction.ASK_CLARIFICATION, updates)
            if _AFFIRM.search(text):
                return self._proposal(Intent.CONFIRMATION, NextAction.CONFIRM, updates)

        intent = Intent.CORRECTION if corrected else Intent.PROVIDE_INFORMATION
        if not updates and not declined:
            return self._proposal(Intent.UNCLEAR, NextAction.ASK_CLARIFICATION, updates)
        return self._proposal(
            intent, NextAction.ASK_NEXT_FIELD, updates, corrected=corrected, declined=declined
        )

    # --- extraction helpers --------------------------------------------------------------------

    @staticmethod
    def _service(text: str, context: TurnContext, updates: dict[str, str]) -> None:
        service = _first(_SERVICES, text)
        if service and service in context.services:
            updates[F.REQUESTED_SERVICE] = service

    @staticmethod
    def _contact(
        text: str,
        context: TurnContext,
        updates: dict[str, str],
        corrected: list[IntakeField],
        declined: list[IntakeField],
    ) -> None:
        email, phone = find_email(text), find_phone(text)
        if email:
            updates[F.EMAIL] = email
        if phone:
            updates[F.PHONE] = phone
        if re.search(r"email (?:is best|me|please)|by email|e-?mail is (?:best|fine)", text):
            updates[F.PREFERRED_CONTACT_CHANNEL] = "email"
        elif re.search(r"call me|phone call|by phone|text me", text):
            updates[F.PREFERRED_CONTACT_CHANNEL] = "phone"
        if re.search(r"rather not|don'?t (?:have|use)|no email|not do email", text):
            if "email" in text and not email:
                declined.append(F.EMAIL)
            elif ("phone" in text or "number" in text) and not phone:
                declined.append(F.PHONE)
        if _CORRECTION.search(text):
            corrected.extend(
                f for f in (F.EMAIL, F.PHONE) if f in updates and f in context.known_values
            )

    @staticmethod
    def _preferences(text: str, context: TurnContext, updates: dict[str, str]) -> None:
        day = find_weekday_date(text, context.clinic_today)
        if day:
            updates[F.PREFERRED_DATE] = day.isoformat()
        at = find_time(text)  # "same time" finds nothing, so the existing time is kept
        if at:
            updates[F.PREFERRED_TIME] = at

    @staticmethod
    def _proposal(
        intent: Intent,
        action: NextAction,
        updates: dict[str, str],
        *,
        corrected: list[IntakeField] | None = None,
        declined: list[IntakeField] | None = None,
        escalate: bool = False,
    ) -> TurnProposal:
        return TurnProposal(
            assistant_response="(composed by the orchestrator)",
            intent=intent,
            field_updates=FieldUpdates.model_validate(updates),
            corrected_fields=corrected or [],
            declined_fields=declined or [],
            next_action=action,
            confidence=0.95 if updates or declined else 0.5,
            requires_escalation=escalate,
            escalation_reason="urgent_symptoms" if escalate else None,
        )
