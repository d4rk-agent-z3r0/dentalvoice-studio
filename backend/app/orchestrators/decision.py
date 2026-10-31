# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Decide where a conversation goes after a caller turn. Pure: no I/O.

Inputs are the current state, the validated proposal and the intake after the proposal's values
were validated and applied. The model's ``next_action`` is a request, honoured only when the
intake and the state machine agree. The model never names a state.
"""

from dataclasses import dataclass

from app.domain.enums import ConversationState
from app.schemas.proposal import NextAction, TurnProposal
from app.services.intake.service import IntakeChanges
from app.services.intake.stages import FIELD_STAGE, LiveValues, intake_complete, stage_complete
from app.state_machine.machine import COLLECTION_STAGES, FLOW

S = ConversationState
_WALKABLE = (S.INTRODUCTION, *COLLECTION_STAGES)


@dataclass(frozen=True)
class Decision:
    path: list[ConversationState]  # every state entered this turn, in order
    clarification: bool  # reply should ask the caller to clarify rather than move on
    ignored_action: NextAction | None  # a requested action the application refused

    def final_state(self, current: ConversationState) -> ConversationState:
        return self.path[-1] if self.path else current


def decide(
    state: ConversationState,
    proposal: TurnProposal,
    changes: IntakeChanges,
    values: LiveValues,
) -> Decision:
    path: list[ConversationState] = []
    current = state
    action = proposal.next_action

    # The caller's first utterance is their introduction, whatever it contains.
    if current is S.GREETING:
        path.append(S.INTRODUCTION)
        current = S.INTRODUCTION

    # Escalation is the conservative choice and is always honoured; ending likewise.
    if proposal.requires_escalation or action is NextAction.ESCALATE:
        return Decision([*path, S.ESCALATED], clarification=False, ignored_action=None)
    if action is NextAction.END:
        return Decision([*path, S.ABANDONED], clarification=False, ignored_action=None)

    ignored: NextAction | None = None
    if current in (S.INFORMATION_REVIEW, S.CONFIRMATION_PENDING):
        if changes.changed_fields:
            # A correction re-opens the earliest affected stage; the walk below brings the call
            # forward again, so the caller always re-reviews before confirming.
            earliest = min((FIELD_STAGE[f] for f in changes.changed_fields), key=FLOW.index)
            path.append(earliest)
            current = earliest
        elif action is NextAction.CONFIRM and intake_complete(values):
            target = S.CONFIRMATION_PENDING if current is S.INFORMATION_REVIEW else S.COMPLETED
            return Decision([*path, target], clarification=False, ignored_action=None)
        else:
            if action is NextAction.CONFIRM:
                ignored = action  # cannot confirm an incomplete intake
            return Decision(path, clarification=True, ignored_action=ignored)
    elif action in (NextAction.CONFIRM, NextAction.REQUEST_CONFIRMATION):
        ignored = action  # confirmation is only possible from review

    while current in _WALKABLE and stage_complete(current, values):
        following = FLOW[FLOW.index(current) + 1]
        if following is S.INFORMATION_REVIEW and not intake_complete(values):
            break
        path.append(following)
        current = following

    clarification = (
        action is NextAction.ASK_CLARIFICATION and not changes.changed_fields and not path
    )
    return Decision(path, clarification=clarification, ignored_action=ignored)
