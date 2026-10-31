# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The orchestrator's state decision: model actions are requests, never commands."""

import pytest

from app.domain.enums import ConversationState, IntakeField, IntakeFieldStatus
from app.orchestrators.decision import decide
from app.schemas.proposal import Intent, NextAction, TurnProposal
from app.services.intake.service import IntakeChanges
from app.services.intake.stages import LiveValues

S = ConversationState
F = IntakeField
P = IntakeFieldStatus.PROVIDED

COMPLETE: dict[IntakeField, tuple[str | None, IntakeFieldStatus]] = {
    F.FIRST_NAME: ("Ava", P),
    F.LAST_NAME: ("Lindqvist", P),
    F.PATIENT_TYPE: ("new", P),
    F.PREFERRED_CONTACT_CHANNEL: ("email", P),
    F.EMAIL: ("ava@example.com", P),
    F.PHONE: ("+1-555-0101", P),
    F.VISIT_REASON: ("cleaning", P),
    F.REQUESTED_SERVICE: ("hygiene_cleaning", P),
    F.PREFERRED_DATE: ("2026-11-03", P),
    F.PREFERRED_TIME: ("10:00", P),
}


def proposal(action: NextAction, *, escalate: bool = False) -> TurnProposal:
    return TurnProposal(
        assistant_response="…",
        intent=Intent.PROVIDE_INFORMATION,
        next_action=action,
        confidence=0.9,
        requires_escalation=escalate,
    )


def only(*fields: IntakeField) -> LiveValues:
    return {f: COMPLETE[f] for f in fields}


def test_first_utterance_is_the_introduction_then_walks_satisfied_stages() -> None:
    decision = decide(
        S.GREETING, proposal(NextAction.ASK_NEXT_FIELD), IntakeChanges(), only(F.PATIENT_TYPE)
    )
    assert decision.path == [S.INTRODUCTION, S.IDENTITY_COLLECTION]


def test_no_progress_when_the_current_stage_is_incomplete() -> None:
    decision = decide(
        S.CONTACT_DETAILS,
        proposal(NextAction.ASK_NEXT_FIELD),
        IntakeChanges(),
        only(F.PATIENT_TYPE, F.FIRST_NAME, F.LAST_NAME, F.EMAIL),
    )
    assert decision.path == []


@pytest.mark.parametrize("state", [S.GREETING, S.CONTACT_DETAILS, S.CONFIRMATION_PENDING])
def test_escalation_is_always_honoured(state: ConversationState) -> None:
    decision = decide(
        state, proposal(NextAction.ASK_NEXT_FIELD, escalate=True), IntakeChanges(), {}
    )
    assert decision.path[-1] is S.ESCALATED


def test_model_cannot_confirm_from_a_collection_stage() -> None:
    decision = decide(
        S.APPOINTMENT_PREFERENCES, proposal(NextAction.CONFIRM), IntakeChanges(), only(F.FIRST_NAME)
    )
    assert decision.path == []
    assert decision.ignored_action is NextAction.CONFIRM


def test_model_cannot_confirm_an_incomplete_review() -> None:
    incomplete = dict(COMPLETE)
    del incomplete[F.PREFERRED_TIME]
    decision = decide(
        S.INFORMATION_REVIEW, proposal(NextAction.CONFIRM), IntakeChanges(), incomplete
    )
    assert decision.path == []
    assert decision.ignored_action is NextAction.CONFIRM


def test_confirmation_needs_two_steps() -> None:
    first = decide(S.INFORMATION_REVIEW, proposal(NextAction.CONFIRM), IntakeChanges(), COMPLETE)
    second = decide(S.CONFIRMATION_PENDING, proposal(NextAction.CONFIRM), IntakeChanges(), COMPLETE)
    assert first.path == [S.CONFIRMATION_PENDING]
    assert second.path == [S.COMPLETED]


@pytest.mark.parametrize("state", [S.INFORMATION_REVIEW, S.CONFIRMATION_PENDING])
def test_correction_during_review_reopens_the_stage_then_returns_to_review(
    state: ConversationState,
) -> None:
    changes = IntakeChanges(corrected=[F.PREFERRED_DATE])
    decision = decide(state, proposal(NextAction.ASK_NEXT_FIELD), changes, COMPLETE)
    assert decision.path == [S.APPOINTMENT_PREFERENCES, S.INFORMATION_REVIEW]


def test_correction_of_an_early_field_walks_back_through_every_later_stage() -> None:
    changes = IntakeChanges(corrected=[F.EMAIL])
    decision = decide(S.INFORMATION_REVIEW, proposal(NextAction.ASK_NEXT_FIELD), changes, COMPLETE)
    assert decision.path == [
        S.CONTACT_DETAILS,
        S.VISIT_REASON,
        S.APPOINTMENT_PREFERENCES,
        S.INFORMATION_REVIEW,
    ]


def test_end_abandons() -> None:
    assert decide(S.VISIT_REASON, proposal(NextAction.END), IntakeChanges(), {}).path == [
        S.ABANDONED
    ]


def test_review_is_not_entered_while_an_earlier_field_is_missing() -> None:
    values = dict(COMPLETE)
    values[F.EMAIL] = (None, IntakeFieldStatus.NOT_PROVIDED)  # the preferred channel, declined
    decision = decide(
        S.APPOINTMENT_PREFERENCES, proposal(NextAction.ASK_NEXT_FIELD), IntakeChanges(), values
    )
    assert decision.path == []
