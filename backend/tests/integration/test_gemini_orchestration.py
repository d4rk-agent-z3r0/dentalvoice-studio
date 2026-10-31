# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Gemini proposals through the real orchestrator and database: the model's words may be spoken,
but its actions are still only requests, and its failures surface as errors."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode, Settings
from app.demo.seed import seed
from app.domain.enums import ConversationState
from app.integrations.llm.base import ProviderUnavailableError
from app.integrations.llm.mock import MockConversationProvider
from app.main import create_app
from app.orchestrators.conversation import ConversationOrchestrator
from app.orchestrators.responses import ESCALATION_MESSAGE
from app.services.conversations import ConversationService
from tests.contract.gemini_fake import FakeGemini, proposal_response
from tests.support.api import DemoClinic, bearer, load_clinic, token_for

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


def proposal(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "assistant_response": "Lovely to hear from you! May I have your first and last name?",
        "intent": "provide_information",
        "field_updates": {"patient_type": "new", "requested_service": "hygiene_cleaning"},
        "next_action": "ASK_NEXT_FIELD",
        "confidence": 0.93,
        "requires_escalation": False,
    }
    return {**base, **overrides}


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


async def test_model_reply_is_spoken_and_usage_is_stored(session_factory: SessionFactory) -> None:
    clinic, conversation_id = await _started(session_factory)
    fake = FakeGemini((200, proposal_response(proposal(), usage=(731, 58))))
    orchestrator = ConversationOrchestrator(session_factory, fake.provider())

    result = await orchestrator.handle_caller_turn(
        clinic.id, conversation_id, "Hi, I'm new and I'd like a cleaning."
    )

    assert result.reply == "Lovely to hear from you! May I have your first and last name?"
    assert result.state is ConversationState.IDENTITY_COLLECTION
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    reply_turn = detail.turns[-1]
    assert (reply_turn.prompt_tokens, reply_turn.output_tokens, reply_turn.llm_attempts) == (
        731,
        58,
        1,
    )
    assert reply_turn.llm_ms is not None


async def test_model_cannot_confirm_from_a_collection_stage(
    session_factory: SessionFactory,
) -> None:
    clinic, conversation_id = await _started(session_factory)
    eager = proposal(
        assistant_response="Great, your appointment is booked and confirmed!",
        next_action="CONFIRM",
        intent="confirmation",
    )
    fake = FakeGemini((200, proposal_response(eager)))
    orchestrator = ConversationOrchestrator(session_factory, fake.provider())

    result = await orchestrator.handle_caller_turn(
        clinic.id, conversation_id, "I'm new, just confirm everything."
    )

    assert result.state is ConversationState.IDENTITY_COLLECTION
    assert "confirmed" not in result.reply.lower()  # the model's claim is never spoken
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    assert "proposal_action_ignored" in [e.type for e in detail.events]


async def test_model_values_are_validated_like_any_other(session_factory: SessionFactory) -> None:
    clinic, conversation_id = await _started(session_factory)
    fake = FakeGemini(
        (200, proposal_response(proposal())),
        (200, proposal_response(proposal(field_updates={"first_name": "Ava", "last_name": "L"}))),
        (
            200,
            proposal_response(
                proposal(
                    assistant_response="Thanks! I've saved ava@gmail.com.",
                    field_updates={"email": "ava@gmail.com", "preferred_contact_channel": "email"},
                )
            ),
        ),
    )
    orchestrator = ConversationOrchestrator(session_factory, fake.provider())
    for text in ("I'm new.", "Ava L.", "my email is ava at gmail dot com"):
        result = await orchestrator.handle_caller_turn(clinic.id, conversation_id, text)

    assert "email" in result.rejected_fields
    assert "gmail" not in result.reply  # a reply built around a rejected value is replaced
    assert "couldn't use that email address" in result.reply


async def test_escalation_uses_the_fixed_safety_message(session_factory: SessionFactory) -> None:
    clinic, conversation_id = await _started(session_factory)
    urgent = proposal(
        assistant_response="You should take ibuprofen and rinse with salt water.",
        intent="urgent_symptoms",
        field_updates={},
        next_action="ESCALATE",
        requires_escalation=True,
        escalation_reason="urgent_symptoms",
    )
    fake = FakeGemini((200, proposal_response(urgent)))
    orchestrator = ConversationOrchestrator(session_factory, fake.provider())

    result = await orchestrator.handle_caller_turn(
        clinic.id, conversation_id, "My jaw is swollen and I can't swallow."
    )

    assert result.state is ConversationState.ESCALATED
    assert result.reply == ESCALATION_MESSAGE  # never the model's (clinical) text


@asynccontextmanager
async def _client_with(
    settings: Settings, orchestrator_factory: Any
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.orchestrator = orchestrator_factory(app.state.session_factory)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_outage_reaches_the_client_as_503_and_changes_nothing(
    session_factory: SessionFactory, database_settings: Settings
) -> None:
    clinic, conversation_id = await _started(session_factory)
    fake = FakeGemini(*[(503, "error_503.json")] * 2)

    async def no_wait(_: float) -> None:
        return None

    headers = bearer(
        await token_for(session_factory, database_settings, "demo.staff@example.com", clinic.id)
    )
    async with _client_with(
        database_settings,
        lambda sf: ConversationOrchestrator(sf, fake.provider(max_attempts=2, sleep=no_wait)),
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/turns",
            json={"text": "I'm a new patient."},
            headers=headers,
        )

    body = response.json()["error"]
    assert (response.status_code, body["code"], body["provider"]) == (
        503,
        ProviderUnavailableError.code,
        "gemini",
    )
    assert "503" not in body["message"]  # upstream details stay in the logs
    detail = await ConversationService(session_factory).detail(clinic.id, conversation_id)
    assert detail.conversation.state is ConversationState.GREETING
    assert detail.intake == []
    assert "provider_error" in [e.type for e in detail.events]
