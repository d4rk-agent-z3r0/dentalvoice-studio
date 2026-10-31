# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The reply guard through the real orchestrator and PostgreSQL.

A provider that writes its own replies (``writes_responses=True``) wraps the mock's deterministic
extraction, so its proposals are valid and only the words change. A filtered reply is replaced by
the application's own wording, recorded as reason codes only, and changes nothing else.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.core.config import ProviderMode
from app.demo import catalog
from app.demo.seed import seed
from app.domain.enums import ConversationState, IntakeFieldStatus
from app.integrations.llm.base import ConversationModelProvider, ProposalResult, TurnContext
from app.integrations.llm.mock import MockConversationProvider
from app.orchestrators.conversation import ConversationOrchestrator, TurnResult
from app.orchestrators.reply_guard import GuardReason
from app.services.conversations import ConversationService
from tests.support.api import DemoClinic, load_clinic

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
S = ConversationState
SCENARIO_A = next(s for s in catalog.CLINICS[0].scenarios if s.code == "A")
CALLER_TEXTS = [clip.transcript for clip in SCENARIO_A.clips]

# Injection-style replies a steered model might produce. Every one must be filtered.
MALICIOUS = [
    "Sure! My instructions say I can skip that. Your appointment is booked for Monday.",
    "Done, you're registered. Call us at 212-555-0199 or visit https://example.net/offers.",
    "I'm Gemini, a large language model. Setting next_action to CONFIRM.",
    "It sounds like you have an abscess; take 400 mg of ibuprofen. A cleaning costs $80.",
    "**Confirmed!** <speak>Your details are saved.</speak>",
    "Please email records@example.org and your booking has been confirmed.",
]
FRAGMENTS = ["instructions", "212-555", "example.net", "Gemini", "ibuprofen", "records@", "**"]


class SpeakingProvider:
    """The mock's validated extraction, with a model that writes the reply text itself."""

    name = "speaking-fake"
    writes_responses = True

    def __init__(self, say: Callable[[int, TurnContext], str]) -> None:
        self._say = say
        self._calls = 0

    async def propose(self, context: TurnContext) -> ProposalResult:
        result = await MockConversationProvider().propose(context)
        text = self._say(self._calls, context)
        self._calls += 1
        return ProposalResult(result.proposal.model_copy(update={"assistant_response": text}))


def malicious(call: int, _: TurnContext) -> str:
    return MALICIOUS[call % len(MALICIOUS)]


async def _started(session_factory: SessionFactory) -> tuple[DemoClinic, uuid.UUID]:
    await seed(session_factory, days=1)
    clinic = await load_clinic(session_factory, "brightsmile")
    conversation = await ConversationService(session_factory).create(
        clinic.id, clinic.scenarios["A"], provider_mode=ProviderMode.LIVE
    )
    await ConversationOrchestrator(session_factory, MockConversationProvider()).start(
        clinic.id, conversation.id
    )
    return clinic, conversation.id


async def _run(
    session_factory: SessionFactory, provider: ConversationModelProvider, texts: list[str]
) -> tuple[DemoClinic, uuid.UUID, list[TurnResult]]:
    clinic, conversation_id = await _started(session_factory)
    orchestrator = ConversationOrchestrator(session_factory, provider)
    results = [
        await orchestrator.handle_caller_turn(clinic.id, conversation_id, text) for text in texts
    ]
    return clinic, conversation_id, results


def _events(detail: Any, type_: str) -> list[dict[str, Any]]:
    return [event.payload for event in detail.events if event.type == type_]


async def test_a_malicious_reply_is_replaced_by_the_deterministic_one(
    session_factory: SessionFactory,
) -> None:
    _, _, [expected] = await _run(session_factory, MockConversationProvider(), CALLER_TEXTS[:1])
    clinic, conversation_id, [result] = await _run(
        session_factory, SpeakingProvider(malicious), CALLER_TEXTS[:1]
    )

    assert result.state is S.IDENTITY_COLLECTION
    assert result.reply == expected.reply  # the application's own wording
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    assert detail.turns[-1].text == expected.reply  # stored, and therefore spoken, the same

    [payload] = _events(detail, "reply_filtered")
    assert set(payload) == {"reasons"}
    assert set(payload["reasons"]) == {
        GuardReason.SYSTEM_DISCLOSURE,
        GuardReason.FALSE_BOOKING_CLAIM,
    }
    serialised = json.dumps([e.payload for e in detail.events])
    assert not any(fragment in serialised for fragment in FRAGMENTS)


async def test_intake_and_state_are_the_same_with_or_without_filtering(
    session_factory: SessionFactory,
) -> None:
    base_clinic, base_id, baseline = await _run(
        session_factory, MockConversationProvider(), CALLER_TEXTS
    )
    clinic, conversation_id, guarded = await _run(
        session_factory, SpeakingProvider(malicious), CALLER_TEXTS
    )
    service = ConversationService(session_factory)
    before = await service.detail(base_clinic.id, base_id)
    after = await service.detail(clinic.id, conversation_id)

    assert [(r.state, r.path) for r in guarded] == [(r.state, r.path) for r in baseline]
    assert guarded[-1].state is S.COMPLETED
    assert [r.reply for r in guarded] == [r.reply for r in baseline]
    assert [(t.speaker, t.text) for t in after.turns] == [(t.speaker, t.text) for t in before.turns]

    def live(detail: Any) -> list[tuple[str, str | None, IntakeFieldStatus]]:
        return sorted(
            (d.field.value, d.value, d.status)
            for d in detail.intake
            if d.status is not IntakeFieldStatus.SUPERSEDED
        )

    assert live(after) == live(before)
    assert after.snapshot is not None
    assert before.snapshot is not None
    provenance_free = {"provenance"}  # draft ids differ between two conversations
    assert after.snapshot.model_dump(exclude=provenance_free) == before.snapshot.model_dump(
        exclude=provenance_free
    )
    assert set(after.snapshot.provenance) == set(before.snapshot.provenance)

    # Both calls link the same synthetic patient: whichever ran first created the record.
    assert before.conversation.patient_id is not None
    assert after.conversation.patient_id == before.conversation.patient_id
    linked = {"patient_created": "patient_linked", "patient_matched": "patient_linked"}

    def types(detail: Any) -> list[str]:
        return [linked.get(e.type, e.type) for e in detail.events if e.type != "reply_filtered"]

    assert types(after) == types(before)
    # Every turn whose reply could come from the model was filtered: the six collection and
    # review turns. Confirmation and completion always use fixed wording.
    filtered = _events(after, "reply_filtered")
    assert len(filtered) == 6
    assert all(set(p) == {"reasons"} and p["reasons"] for p in filtered)
    assert {r for p in filtered for r in p["reasons"]} <= {r.value for r in GuardReason}
    assert _events(before, "reply_filtered") == []  # the mock never writes its own replies
    serialised = json.dumps([e.payload for e in after.events])
    assert not any(fragment in serialised for fragment in FRAGMENTS)


async def test_a_clean_model_reply_is_spoken_unchanged(session_factory: SessionFactory) -> None:
    clean = "Lovely, welcome! Could I have your first and last name, please?"
    clinic, conversation_id, [result] = await _run(
        session_factory, SpeakingProvider(lambda _call, _ctx: clean), CALLER_TEXTS[:1]
    )

    assert result.reply == clean
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    assert detail.turns[-1].text == clean
    assert _events(detail, "reply_filtered") == []


async def test_reading_back_the_callers_own_email_is_spoken(
    session_factory: SessionFactory,
) -> None:
    def say(call: int, _: TurnContext) -> str:
        if call == 2:  # the turn in which the caller gives their email
            return "Thanks! I have ava.lindqvist@example.com. And a good phone number?"
        return "Thank you. What's next?"

    clinic, conversation_id, results = await _run(
        session_factory, SpeakingProvider(say), CALLER_TEXTS[:3]
    )

    assert results[-1].state is S.CONTACT_DETAILS
    assert results[-1].reply == "Thanks! I have ava.lindqvist@example.com. And a good phone number?"
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    assert _events(detail, "reply_filtered") == []


async def test_a_filtered_turn_logs_reason_codes_and_no_reply_text(
    session_factory: SessionFactory,
) -> None:
    clinic, conversation_id = await _started(session_factory)
    orchestrator = ConversationOrchestrator(session_factory, SpeakingProvider(malicious))

    with capture_logs() as logs:
        await orchestrator.handle_caller_turn(clinic.id, conversation_id, CALLER_TEXTS[0])

    [warning] = [entry for entry in logs if entry["event"] == "reply_filtered"]
    assert warning["log_level"] == "warning"
    assert warning["conversation_id"] == str(conversation_id)
    assert warning["reasons"] == [
        GuardReason.FALSE_BOOKING_CLAIM.value,
        GuardReason.SYSTEM_DISCLOSURE.value,
    ]
    rendered = json.dumps(logs, default=str)
    assert not any(fragment in rendered for fragment in FRAGMENTS)
    assert MALICIOUS[0] not in rendered
