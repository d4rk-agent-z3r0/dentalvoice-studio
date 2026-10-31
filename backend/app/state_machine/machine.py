# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The conversation state machine: explicit allowed transitions and nothing else.

Pure Python with no I/O, so it can be tested exhaustively and nothing outside it (in particular
model output) can move a conversation along an edge that is not listed here.

Shape of a call::

    CREATED → GREETING → INTRODUCTION → collection stages → INFORMATION_REVIEW
            → CONFIRMATION_PENDING → COMPLETED

Collection stages are IDENTITY_COLLECTION, CONTACT_DETAILS, VISIT_REASON and
APPOINTMENT_PREFERENCES, in that order. Within them a call may move forward past stages the caller
has already satisfied, but it can never jump past INFORMATION_REVIEW, and COMPLETED is only
reachable from CONFIRMATION_PENDING. During review or confirmation a correction moves the call
back to the stage that owns the corrected field. Any non-terminal state may go to ESCALATED or
ABANDONED. Terminal states have no outgoing edges.
"""

from collections.abc import Iterable, Mapping

from app.domain.enums import TERMINAL_STATES, ConversationState
from app.domain.errors import InvalidStateTransitionError

S = ConversationState

COLLECTION_STAGES: tuple[ConversationState, ...] = (
    S.IDENTITY_COLLECTION,
    S.CONTACT_DETAILS,
    S.VISIT_REASON,
    S.APPOINTMENT_PREFERENCES,
)

# Every state a live call passes through, in order; used to order "forward" moves.
FLOW: tuple[ConversationState, ...] = (
    S.CREATED,
    S.GREETING,
    S.INTRODUCTION,
    *COLLECTION_STAGES,
    S.INFORMATION_REVIEW,
    S.CONFIRMATION_PENDING,
    S.COMPLETED,
)

_EXITS = frozenset({S.ESCALATED, S.ABANDONED})


def _build_transitions() -> dict[ConversationState, frozenset[ConversationState]]:
    table: dict[ConversationState, set[ConversationState]] = {
        S.CREATED: {S.GREETING},
        S.GREETING: {S.INTRODUCTION},
        S.INTRODUCTION: {S.IDENTITY_COLLECTION},
        S.INFORMATION_REVIEW: {S.CONFIRMATION_PENDING, *COLLECTION_STAGES},
        S.CONFIRMATION_PENDING: {S.COMPLETED, S.INFORMATION_REVIEW, *COLLECTION_STAGES},
    }
    for index, stage in enumerate(COLLECTION_STAGES):
        later = set(COLLECTION_STAGES[index + 1 :])
        # Forward only; a correction during collection updates the field without moving back.
        table[stage] = {*later, S.INFORMATION_REVIEW}
    for state in table:
        table[state] |= _EXITS
    for terminal in TERMINAL_STATES:
        table[terminal] = set()
    return {state: frozenset(targets) for state, targets in table.items()}


TRANSITIONS: Mapping[ConversationState, frozenset[ConversationState]] = _build_transitions()


def can_transition(current: ConversationState, target: ConversationState) -> bool:
    return target in TRANSITIONS[current]


def assert_transition(current: ConversationState, target: ConversationState) -> None:
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"Transition {current.value} → {target.value} is not allowed."
        )


def validate_path(start: ConversationState, path: Iterable[ConversationState]) -> None:
    """Raise unless every consecutive step from ``start`` through ``path`` is allowed."""
    current = start
    for target in path:
        assert_transition(current, target)
        current = target


def is_terminal(state: ConversationState) -> bool:
    return state in TERMINAL_STATES
