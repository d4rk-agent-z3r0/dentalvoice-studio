# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Exhaustive checks of the transition table: every pair of states is either allowed or refused."""

import itertools

import pytest

from app.demo import catalog
from app.domain.enums import TERMINAL_STATES, ConversationState
from app.domain.errors import InvalidStateTransitionError
from app.state_machine.machine import (
    COLLECTION_STAGES,
    TRANSITIONS,
    assert_transition,
    can_transition,
    is_terminal,
    validate_path,
)

S = ConversationState
ALL_PAIRS = list(itertools.product(S, S))

# The complete allowed set, written out independently of the table-building code.
EXPECTED_ALLOWED = {
    (S.CREATED, S.GREETING),
    (S.GREETING, S.INTRODUCTION),
    (S.INTRODUCTION, S.IDENTITY_COLLECTION),
    (S.IDENTITY_COLLECTION, S.CONTACT_DETAILS),
    (S.IDENTITY_COLLECTION, S.VISIT_REASON),
    (S.IDENTITY_COLLECTION, S.APPOINTMENT_PREFERENCES),
    (S.IDENTITY_COLLECTION, S.INFORMATION_REVIEW),
    (S.CONTACT_DETAILS, S.VISIT_REASON),
    (S.CONTACT_DETAILS, S.APPOINTMENT_PREFERENCES),
    (S.CONTACT_DETAILS, S.INFORMATION_REVIEW),
    (S.VISIT_REASON, S.APPOINTMENT_PREFERENCES),
    (S.VISIT_REASON, S.INFORMATION_REVIEW),
    (S.APPOINTMENT_PREFERENCES, S.INFORMATION_REVIEW),
    (S.INFORMATION_REVIEW, S.CONFIRMATION_PENDING),
    *((S.INFORMATION_REVIEW, stage) for stage in COLLECTION_STAGES),
    (S.CONFIRMATION_PENDING, S.COMPLETED),
    (S.CONFIRMATION_PENDING, S.INFORMATION_REVIEW),
    *((S.CONFIRMATION_PENDING, stage) for stage in COLLECTION_STAGES),
    *(
        (state, exit_state)
        for state in S
        if state not in TERMINAL_STATES
        for exit_state in (S.ESCALATED, S.ABANDONED)
    ),
}


def test_table_covers_every_state() -> None:
    assert set(TRANSITIONS) == set(S)


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS, ids=lambda s: s.value)
def test_each_pair_is_allowed_only_if_listed(
    current: ConversationState, target: ConversationState
) -> None:
    allowed = (current, target) in EXPECTED_ALLOWED
    assert can_transition(current, target) is allowed
    if allowed:
        assert_transition(current, target)
    else:
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(current, target)


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_terminal_states_are_sticky(state: ConversationState) -> None:
    assert is_terminal(state)
    assert TRANSITIONS[state] == frozenset()


@pytest.mark.parametrize(
    "target",
    [S.COMPLETED, S.CONFIRMATION_PENDING],
)
def test_completion_cannot_skip_review(target: ConversationState) -> None:
    for stage in (S.GREETING, S.INTRODUCTION, *COLLECTION_STAGES):
        assert not can_transition(stage, target)
    assert not can_transition(S.INFORMATION_REVIEW, S.COMPLETED)


def test_collection_never_moves_backwards_on_its_own() -> None:
    for earlier, later in itertools.combinations(COLLECTION_STAGES, 2):
        assert not can_transition(later, earlier)


def test_no_state_returns_to_created_or_greeting() -> None:
    for state in S:
        assert not can_transition(state, S.CREATED)
        if state is not S.CREATED:
            assert not can_transition(state, S.GREETING)


@pytest.mark.parametrize(
    "scenario",
    [s for c in catalog.CLINICS for s in c.scenarios],
    ids=lambda s: s.code + "-" + s.clips[0].id,
)
def test_every_scenario_expectation_is_a_legal_path(scenario: catalog.Scenario) -> None:
    validate_path(scenario.states[0], scenario.states[1:])


def test_validate_path_reports_the_illegal_step() -> None:
    with pytest.raises(InvalidStateTransitionError, match="GREETING → COMPLETED"):
        validate_path(S.CREATED, [S.GREETING, S.COMPLETED])
