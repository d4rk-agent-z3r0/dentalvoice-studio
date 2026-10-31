# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The voice WebSocket end to end: real uvicorn, real socket, real database, mock providers."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import websockets
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from websockets.exceptions import InvalidStatus

from app.core.config import Settings
from app.demo import catalog
from app.demo.seed import seed
from app.main import create_app
from app.models import WsTicket
from tests.support.api import DemoClinic, bearer, load_clinic, token_for
from tests.support.live_server import VoiceClient, live_server, ws_url

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
SCENARIO_A = catalog.BRIGHTSMILE.scenarios[0]


@pytest.fixture
async def server(
    database_settings: Settings, session_factory: SessionFactory
) -> AsyncIterator[str]:
    await seed(session_factory, days=1)
    async with live_server(create_app(database_settings)) as base:
        yield base


@pytest.fixture
async def clinic(session_factory: SessionFactory) -> DemoClinic:
    return await load_clinic(session_factory, "brightsmile")


@pytest.fixture
async def http(
    server: str,
    clinic: DemoClinic,
    session_factory: SessionFactory,
    database_settings: Settings,
) -> AsyncIterator[httpx.AsyncClient]:
    token = await token_for(session_factory, database_settings, "demo.staff@example.com", clinic.id)
    async with httpx.AsyncClient(base_url=server, headers=bearer(token)) as client:
        yield client


async def _conversation(http: httpx.AsyncClient, clinic: DemoClinic, code: str = "A") -> str:
    created = await http.post(
        "/api/v1/conversations", json={"scenario_id": str(clinic.scenarios[code])}
    )
    conversation_id: str = created.json()["id"]
    return conversation_id


async def _ticket(http: httpx.AsyncClient, conversation_id: str) -> str:
    response = await http.post(f"/api/v1/conversations/{conversation_id}/ws-ticket")
    assert response.status_code == 200, response.text
    assert response.json()["expires_in"] == 60
    ticket: str = response.json()["ticket"]
    return ticket


async def test_full_scenario_over_the_socket(
    server: str, http: httpx.AsyncClient, clinic: DemoClinic
) -> None:
    conversation_id = await _conversation(http, clinic)
    ticket = await _ticket(http, conversation_id)

    async with websockets.connect(ws_url(server, conversation_id, ticket)) as connection:
        client = VoiceClient(connection)
        ready = await client.until(lambda m: m["type"] == "ready")
        assert ready["audio"] == {"sample_rate": 24000, "encoding": "linear16", "channels": 1}
        await client.send("start")
        await client.turn_done()
        for _ in SCENARIO_A.clips:
            await client.send("next_clip")
            await client.turn_done()
        closed = await client.until(lambda m: m["type"] == "closed")
        assert closed["state"] == "COMPLETED"
        with pytest.raises(websockets.ConnectionClosedOK):
            await connection.recv()  # the server closes the socket normally after the call ends

    received = client.received
    states = ["CREATED", *[s for m in received.of("state") for s in m["path"]]]
    assert states == [s.value for s in SCENARIO_A.states]
    # Clips are announced in script order and every utterance is the clip's exact transcript.
    assert [m["clip_id"] for m in received.of("clip")] == [c.id for c in SCENARIO_A.clips]
    assert [m["text"] for m in received.of("utterance.final")] == [
        c.transcript for c in SCENARIO_A.clips
    ]
    assert received.of("transcript.interim")  # shown while audio streams
    assert not received.of("error")
    # Audio frames are tagged with the turn they belong to.
    reply_turns = {m["turn_seq"] for m in received.of("assistant.text")}
    assert {seq for seq, _ in received.frames} == reply_turns
    assert all(size > 0 for _, size in received.frames)
    assert len(received.of("assistant.audio_end")) == len(reply_turns)
    # Latency: measured per stage for every caller turn; the greeting has no STT or LLM stage.
    greeting, *caller_turns = received.of("latency")
    assert greeting["stt_ms"] is None
    assert greeting["tts_first_byte_ms"] is not None
    for report in caller_turns:
        assert all(
            report[k] is not None for k in ("stt_ms", "llm_ms", "tts_first_byte_ms", "total_ms")
        )

    detail = (await http.get(f"/api/v1/conversations/{conversation_id}")).json()
    caller = [t for t in detail["turns"] if t["speaker"] == "caller"]
    replies = [t for t in detail["turns"] if t["speaker"] == "receptionist"]
    assert [t["text"] for t in caller] == [c.transcript for c in SCENARIO_A.clips]
    assert [t["clip_id"] for t in caller] == [c.id for c in SCENARIO_A.clips]
    assert all(t["stt_ms"] is not None for t in caller)
    assert all(t["tts_ms"] is not None for t in replies)
    assert all(t["total_ms"] is not None for t in replies[1:])
    assert detail["snapshot"] is not None


async def test_ticket_is_single_use(
    server: str, http: httpx.AsyncClient, clinic: DemoClinic
) -> None:
    conversation_id = await _conversation(http, clinic)
    ticket = await _ticket(http, conversation_id)
    async with websockets.connect(ws_url(server, conversation_id, ticket)) as connection:
        await VoiceClient(connection).until(lambda m: m["type"] == "ready")
    with pytest.raises(InvalidStatus) as caught:
        async with websockets.connect(ws_url(server, conversation_id, ticket)):
            pass
    assert caught.value.response.status_code == 403


@pytest.mark.parametrize("problem", ["wrong-conversation", "expired", "unknown"])
async def test_bad_tickets_are_refused_before_the_handshake(
    server: str,
    http: httpx.AsyncClient,
    clinic: DemoClinic,
    session_factory: SessionFactory,
    problem: str,
) -> None:
    conversation_id = await _conversation(http, clinic)
    other_id = await _conversation(http, clinic)
    ticket = await _ticket(http, other_id if problem == "wrong-conversation" else conversation_id)
    if problem == "expired":
        async with session_factory.begin() as session:
            past = datetime.now(UTC) - timedelta(minutes=5)
            await session.execute(
                update(WsTicket).values(created_at=past, expires_at=past + timedelta(seconds=60))
            )
    if problem == "unknown":
        ticket = "x" * 43
    with pytest.raises(InvalidStatus) as caught:
        async with websockets.connect(ws_url(server, conversation_id, ticket)):
            pass
    assert caught.value.response.status_code == 403


async def test_client_audio_and_bad_commands_are_refused(
    server: str, http: httpx.AsyncClient, clinic: DemoClinic
) -> None:
    conversation_id = await _conversation(http, clinic)
    ticket = await _ticket(http, conversation_id)
    async with websockets.connect(ws_url(server, conversation_id, ticket)) as connection:
        client = VoiceClient(connection)
        await client.until(lambda m: m["type"] == "ready")
        await connection.send(b"\x00\x01" * 400)
        assert (await client.until(lambda m: m["type"] == "error"))["code"] == "AUDIO_NOT_ACCEPTED"
        for bad in ("not json", '["a list"]', '{"type": "play", "clip_id": "../x"}', "x" * 2000):
            await connection.send(bad)
            assert (await client.until(lambda m: m["type"] == "error"))["code"] == "INVALID_MESSAGE"
        await client.send("next_clip")
        error = await client.until(lambda m: m["type"] == "error")
        assert error["code"] == "INVALID_STATE_TRANSITION"  # must start first


async def test_end_abandons_the_call_and_closes(
    server: str, http: httpx.AsyncClient, clinic: DemoClinic
) -> None:
    conversation_id = await _conversation(http, clinic)
    ticket = await _ticket(http, conversation_id)
    async with websockets.connect(ws_url(server, conversation_id, ticket)) as connection:
        client = VoiceClient(connection)
        await client.until(lambda m: m["type"] == "ready")
        await client.send("start")
        await client.turn_done()
        await client.send("end")
        closed = await client.until(lambda m: m["type"] == "closed")
    assert closed["state"] == "ABANDONED"
    detail = (await http.get(f"/api/v1/conversations/{conversation_id}")).json()
    assert detail["conversation"]["state"] == "ABANDONED"
    # A ticket for a finished call is not issued.
    response = await http.post(f"/api/v1/conversations/{conversation_id}/ws-ticket")
    assert response.status_code == 409


async def test_reconnecting_resumes_with_the_next_clip(
    server: str, http: httpx.AsyncClient, clinic: DemoClinic
) -> None:
    conversation_id = await _conversation(http, clinic)
    async with websockets.connect(
        ws_url(server, conversation_id, await _ticket(http, conversation_id))
    ) as connection:
        client = VoiceClient(connection)
        await client.until(lambda m: m["type"] == "ready")
        await client.send("start")
        await client.turn_done()
        await client.send("next_clip")
        await client.turn_done()
    # Dropped connection; a new socket continues the same call.
    async with websockets.connect(
        ws_url(server, conversation_id, await _ticket(http, conversation_id))
    ) as connection:
        client = VoiceClient(connection)
        ready = await client.until(lambda m: m["type"] == "ready")
        assert ready["state"] == "IDENTITY_COLLECTION"
        await client.send("next_clip")
        clip: dict[str, Any] = await client.until(lambda m: m["type"] == "clip")
        assert clip["clip_id"] == SCENARIO_A.clips[1].id
        await client.turn_done()
