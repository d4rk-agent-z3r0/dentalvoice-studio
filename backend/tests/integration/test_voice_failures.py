# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Voice session fault handling, with providers that fail on purpose.

The session runs against the real orchestrator and PostgreSQL; only the providers and the client
transport are replaced, so every failure path is deterministic.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderMode
from app.demo import catalog
from app.demo.seed import seed
from app.domain.enums import Speaker
from app.integrations.errors import ProviderError, ProviderUnavailableError
from app.integrations.llm.base import ProposalResult, TurnContext
from app.integrations.llm.mock import MockConversationProvider
from app.integrations.speech.base import AudioFormat, TranscriptEvent, TranscriptKind
from app.integrations.speech.mock import MockSpeechToTextProvider, MockTextToSpeechProvider
from app.orchestrators.conversation import ConversationOrchestrator
from app.orchestrators.voice_session import VoiceSession
from app.services.conversations import ConversationService
from app.voice.clips import default_library
from tests.support.api import load_clinic

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]
CLIPS_A = catalog.BRIGHTSMILE.scenarios[0].clips


class Recorder:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.frames: list[int] = []
        self.changed = asyncio.Condition()

    async def send_json(self, data: dict[str, Any]) -> None:
        async with self.changed:
            self.messages.append(data)
            self.changed.notify_all()

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(int.from_bytes(data[:4], "big"))

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == type_]

    async def wait_for(self, type_: str, count: int = 1) -> dict[str, Any]:
        async with asyncio.timeout(10), self.changed:
            await self.changed.wait_for(lambda: len(self.of(type_)) >= count)
            return self.of(type_)[count - 1]


class Commands:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def send(self, type_: str) -> None:
        self._queue.put_nowait({"type": type_})

    def hang_up(self) -> None:
        self._queue.put_nowait(None)  # the client disconnects without "end"

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        while (item := await self._queue.get()) is not None:
            yield item


# --- failing providers -------------------------------------------------------------------------


class OutageSTT:
    """Accepts audio, then fails while results are being read."""

    name = "outage-stt"

    @asynccontextmanager
    async def open_stream(self, *, sample_rate: int) -> AsyncIterator["OutageSTT"]:
        yield self

    async def send_audio(self, chunk: bytes) -> None:
        return None

    async def finish(self) -> None:
        return None

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        yield TranscriptEvent(TranscriptKind.INTERIM, "hi I'd")
        raise ProviderUnavailableError("outage-stt", "connection reset")


class SilentSTT(OutageSTT):
    name = "silent-stt"

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        yield TranscriptEvent(TranscriptKind.UTTERANCE_END)


class BrokenTTS:
    """Streams one chunk, then fails."""

    name = "broken-tts"
    output_format = AudioFormat(sample_rate=24_000)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        yield b"\x00\x00" * 240
        raise ProviderError("broken-tts", "stream interrupted")


class SlowTTS:
    """Speaks slowly and records whether it was cancelled mid-sentence."""

    name = "slow-tts"
    output_format = AudioFormat(sample_rate=24_000)

    def __init__(self) -> None:
        self.cancelled = 0
        self.started = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        try:
            for _ in range(200):
                self.started.set()
                yield b"\x00\x00" * 240
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class FailingModel:
    name = "failing-model"
    writes_responses = False

    async def propose(self, context: TurnContext) -> ProposalResult:
        raise ProviderError("failing-model", "HTTP 400 INVALID_ARGUMENT")


# --- harness -----------------------------------------------------------------------------------


async def _session(
    session_factory: SessionFactory,
    *,
    stt: Any = None,
    tts: Any = None,
    model: Any = None,
) -> tuple[VoiceSession, Recorder, Commands, uuid.UUID, uuid.UUID]:
    await seed(session_factory, days=1)
    clinic = await load_clinic(session_factory, "brightsmile")
    conversation = await ConversationService(session_factory).create(
        clinic.id, clinic.scenarios["A"], provider_mode=ProviderMode.MOCK
    )
    library = default_library()
    recorder, commands = Recorder(), Commands()
    session = VoiceSession(
        clinic_id=clinic.id,
        conversation_id=conversation.id,
        orchestrator=ConversationOrchestrator(session_factory, model or MockConversationProvider()),
        conversations=ConversationService(session_factory),
        stt=stt or MockSpeechToTextProvider(library),
        tts=tts or MockTextToSpeechProvider(),
        library=library,
        out=recorder,
        realtime_factor=0,
    )
    return session, recorder, commands, clinic.id, conversation.id


async def _caller_turns(
    session_factory: SessionFactory, clinic_id: uuid.UUID, cid: uuid.UUID
) -> list[str]:
    detail = await ConversationService(session_factory).detail(clinic_id, cid)
    return [t.text for t in detail.turns if t.speaker is Speaker.CALLER]


async def test_stt_outage_is_reported_and_the_clip_is_replayed(
    session_factory: SessionFactory,
) -> None:
    session, out, commands, clinic_id, cid = await _session(session_factory, stt=OutageSTT())
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")
    await out.wait_for("latency")
    commands.send("next_clip")
    error = await out.wait_for("error")
    commands.send("next_clip")
    await out.wait_for("error", 2)
    commands.send("end")
    await runner

    assert (error["code"], error["provider"]) == ("PROVIDER_UNAVAILABLE", "outage-stt")
    assert not out.of("utterance.final")  # an interim was shown, nothing was committed
    assert await _caller_turns(session_factory, clinic_id, cid) == []
    assert [m["clip_id"] for m in out.of("clip")] == [CLIPS_A[0].id, CLIPS_A[0].id]


async def test_no_speech_is_an_error_not_an_empty_turn(session_factory: SessionFactory) -> None:
    session, out, commands, clinic_id, cid = await _session(session_factory, stt=SilentSTT())
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")
    await out.wait_for("latency")
    commands.send("next_clip")
    error = await out.wait_for("error")
    commands.send("end")
    await runner

    assert error["code"] == "NO_SPEECH"
    assert await _caller_turns(session_factory, clinic_id, cid) == []


async def test_tts_failure_keeps_the_text_reply_and_reports_the_error(
    session_factory: SessionFactory,
) -> None:
    session, out, commands, clinic_id, cid = await _session(session_factory, tts=BrokenTTS())
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")
    error = await out.wait_for("error")
    latency = await out.wait_for("latency")
    commands.send("end")
    await runner

    assert (error["code"], error["provider"]) == ("PROVIDER_ERROR", "broken-tts")
    assert out.of("assistant.text")  # the reply text still reached the client
    assert not out.of("assistant.audio_end")  # no pretence that the audio completed
    assert latency["tts_first_byte_ms"] is not None  # one chunk did arrive
    detail = await ConversationService(session_factory).detail(clinic_id, cid)
    greeting = detail.turns[0]
    assert (greeting.speaker, greeting.tts_ms) == (
        Speaker.RECEPTIONIST,
        latency["tts_first_byte_ms"],
    )


async def test_model_failure_is_reported_and_the_clip_is_replayed(
    session_factory: SessionFactory,
) -> None:
    session, out, commands, clinic_id, cid = await _session(session_factory, model=FailingModel())
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")  # the greeting does not use the model
    await out.wait_for("latency")
    commands.send("next_clip")
    error = await out.wait_for("error")
    commands.send("next_clip")
    await out.wait_for("error", 2)
    commands.send("end")
    await runner

    assert (error["code"], error["provider"]) == ("PROVIDER_ERROR", "failing-model")
    assert [m["clip_id"] for m in out.of("clip")] == [CLIPS_A[0].id, CLIPS_A[0].id]
    assert not out.of("assistant.text")[1:]  # only the greeting was ever spoken
    # Each attempt's caller speech is on record, unanswered; nothing else changed.
    assert await _caller_turns(session_factory, clinic_id, cid) == [CLIPS_A[0].transcript] * 2
    detail = await ConversationService(session_factory).detail(clinic_id, cid)
    assert detail.intake == []  # no value was ever applied
    assert [e.type for e in detail.events].count("provider_error") == 2


async def test_barge_in_cancels_speech_and_drops_the_old_turn(
    session_factory: SessionFactory,
) -> None:
    tts = SlowTTS()
    session, out, commands, _, _ = await _session(session_factory, tts=tts)
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")
    await tts.started.wait()
    commands.send("next_clip")  # interrupt the greeting
    cancelled = await out.wait_for("assistant.audio_cancelled")
    await out.wait_for("utterance.final")
    commands.send("end")
    await runner

    greeting_seq = out.of("assistant.text")[0]["turn_seq"]
    assert cancelled["turn_seq"] == greeting_seq
    assert tts.cancelled >= 1
    first_after_cancel = out.messages.index(cancelled)
    later_turns = {
        m["turn_seq"] for m in out.messages[first_after_cancel:] if m["type"] == "assistant.text"
    }
    assert greeting_seq not in later_turns


async def test_client_disconnect_cancels_speech_in_flight(session_factory: SessionFactory) -> None:
    tts = SlowTTS()
    session, out, commands, _, _ = await _session(session_factory, tts=tts)
    runner = asyncio.create_task(session.run(commands))
    commands.send("start")
    await tts.started.wait()
    commands.hang_up()
    async with asyncio.timeout(5):
        await runner
    assert tts.cancelled == 1
    assert len(out.frames) < 200  # the rest of the sentence was never streamed
