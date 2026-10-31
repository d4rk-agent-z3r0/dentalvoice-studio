# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deepgram streaming speech-to-text against a real local WebSocket server.

The server (``deepgram_fake.FakeListen``) plays back hand-written messages in Deepgram's documented
shapes; the adapter and the ``websockets`` client are unmodified.
"""

import asyncio
import json

import pytest

from app.integrations.errors import ProviderError, ProviderUnavailableError
from app.integrations.speech.base import SpeechStream, TranscriptEvent, TranscriptKind
from app.integrations.speech.deepgram_stt import DeepgramSpeechToTextProvider
from app.voice.assembler import UtteranceAssembler
from app.voice.clips import default_library
from tests.contract.deepgram_fake import (
    TEST_KEY,
    FakeListen,
    ListenPlan,
    unresponsive_server,
)

K = TranscriptKind

TWO_PART_UTTERANCE = ListenPlan(
    on_connect=["stt_speech_started.json"],
    after_first_audio=[
        "stt_results_interim.json",
        "stt_results_final_part1.json",
        "stt_results_interim_part2.json",
    ],
    after_close_stream=[
        "stt_results_final_part2.json",
        "stt_utterance_end.json",
        "stt_results_final_empty.json",
        "stt_metadata.json",
    ],
)


def clip_chunks() -> list[bytes]:
    library = default_library()
    return list(library.get(library.ids()[0]).chunks())


async def send_all(stream: SpeechStream, chunks: list[bytes]) -> None:
    for chunk in chunks:
        await stream.send_audio(chunk)


async def collect(stream: SpeechStream) -> list[TranscriptEvent]:
    return [event async for event in stream.events()]


async def transcribe(provider: DeepgramSpeechToTextProvider) -> list[TranscriptEvent]:
    """Send a whole clip, finish, then read every event (the order the voice tests use)."""
    async with provider.open_stream(sample_rate=16_000) as stream:
        await send_all(stream, clip_chunks())
        await stream.finish()
        return await collect(stream)


# --- request shape -----------------------------------------------------------------------------


async def test_handshake_carries_the_key_only_in_the_authorization_header() -> None:
    async with FakeListen(TWO_PART_UTTERANCE).running() as fake:
        await transcribe(fake.provider())

    record = fake.last
    assert record.headers is not None
    assert record.headers["Authorization"] == f"Token {TEST_KEY}"
    assert TEST_KEY not in record.path
    assert urlsplit_path(record.path) == "/v1/listen"
    assert record.query == {
        "model": ["stt-test-model"],
        "encoding": ["linear16"],
        "sample_rate": ["16000"],
        "channels": ["1"],
        "interim_results": ["true"],
        "endpointing": ["300"],
        "utterance_end_ms": ["1000"],
        "vad_events": ["true"],
        "smart_format": ["true"],
        "punctuate": ["true"],
    }


def urlsplit_path(path: str) -> str:
    return path.split("?", 1)[0]


async def test_audio_arrives_as_binary_frames_then_close_stream_as_text() -> None:
    chunks = clip_chunks()
    async with FakeListen(TWO_PART_UTTERANCE).running() as fake:
        provider = fake.provider()
        async with provider.open_stream(sample_rate=16_000) as stream:
            await send_all(stream, chunks)
            await stream.send_audio(b"")  # empty frames are never sent
            await stream.finish()
            await stream.finish()  # idempotent
            await collect(stream)

    assert bytes(fake.last.audio) == b"".join(chunks)
    assert fake.last.audio_frames == len(chunks)
    assert fake.last.control_types == ["CloseStream"]
    assert json.loads(fake.last.text_frames[0]) == {"type": "CloseStream"}


# --- message mapping ---------------------------------------------------------------------------


async def test_interim_and_split_finals_assemble_into_one_utterance() -> None:
    async with FakeListen(TWO_PART_UTTERANCE).running() as fake:
        events = await transcribe(fake.provider())

    # SpeechStarted and Metadata are informational and produce no events.
    assert [event.kind for event in events] == [
        K.INTERIM,
        K.FINAL,
        K.INTERIM,
        K.FINAL,
        K.UTTERANCE_END,
        K.FINAL,
    ]
    assert events[0] == TranscriptEvent(K.INTERIM, "i'd like to book", confidence=0.71)
    assert events[1] == TranscriptEvent(K.FINAL, "I'd like to book a cleaning,", confidence=0.97)
    assert not any(event.speech_final for event in events)

    assembler = UtteranceAssembler()
    committed = [text for event in events if (text := assembler.add(event)) is not None]
    assert committed == ["I'd like to book a cleaning, next Tuesday morning, please."]
    assert assembler.flush() is None  # the trailing empty final adds nothing


async def test_speech_final_completes_the_utterance_without_utterance_end() -> None:
    plan = ListenPlan(
        after_first_audio=["stt_results_final_speech_final.json"],
        after_close_stream=["stt_utterance_end_already_finalized.json", "stt_metadata.json"],
    )
    async with FakeListen(plan).running() as fake:
        events = await transcribe(fake.provider())

    # UtteranceEnd with last_word_end == -1 is documented as "already finalized": ignored.
    assert events == [TranscriptEvent(K.FINAL, "Yes, that's correct.", True, 0.99)]
    assert UtteranceAssembler().add(events[0]) == "Yes, that's correct."


async def test_events_can_be_read_while_audio_is_still_being_sent() -> None:
    async with FakeListen(TWO_PART_UTTERANCE).running() as fake:
        provider = fake.provider()
        async with provider.open_stream(sample_rate=16_000) as stream:
            reader = asyncio.create_task(collect(stream))
            await send_all(stream, clip_chunks())
            await stream.finish()
            events = await asyncio.wait_for(reader, 2)

    assert [event.kind for event in events][-2:] == [K.UTTERANCE_END, K.FINAL]


async def test_keepalive_is_sent_as_text_while_no_audio_flows() -> None:
    async with FakeListen(TWO_PART_UTTERANCE).running() as fake:
        provider = fake.provider(keepalive_seconds=0.05)
        async with provider.open_stream(sample_rate=16_000) as stream:
            await stream.send_audio(clip_chunks()[0])
            await asyncio.sleep(0.3)
            await stream.finish()
            await collect(stream)

    types = fake.last.control_types
    assert types[-1] == "CloseStream"
    assert len(types) >= 2
    assert set(types[:-1]) == {"KeepAlive"}


# --- handshake failures ------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_handshake_is_a_provider_error_not_retried(status: int) -> None:
    async with FakeListen(ListenPlan(reject_status=status)).running() as fake:
        with pytest.raises(ProviderError) as caught:
            await transcribe(fake.provider())

    assert not isinstance(caught.value, ProviderUnavailableError)
    assert caught.value.code == "PROVIDER_ERROR"
    assert f"HTTP {status} (Invalid credentials.)" in caught.value.message
    assert TEST_KEY not in str(caught.value)
    assert len(fake.connections) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_overloaded_handshake_is_provider_unavailable(status: int) -> None:
    async with FakeListen(ListenPlan(reject_status=status, reject_error="busy")).running() as fake:
        with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
            await transcribe(fake.provider())


async def test_connection_refused_is_provider_unavailable() -> None:
    async with FakeListen().running() as fake:
        url = fake.url  # the port is free again once the server stops
    provider = DeepgramSpeechToTextProvider(
        api_key=TEST_KEY, model="stt-test-model", timeout_seconds=2.0, base_url=url
    )
    with pytest.raises(ProviderUnavailableError, match="connection failed"):
        await transcribe(provider)


async def test_handshake_timeout_is_provider_unavailable() -> None:
    async with unresponsive_server() as url:
        provider = DeepgramSpeechToTextProvider(
            api_key=TEST_KEY, model="stt-test-model", timeout_seconds=0.2, base_url=url
        )
        with pytest.raises(ProviderUnavailableError, match=r"timed out after 0\.2s"):
            await transcribe(provider)


# --- failures mid-stream -----------------------------------------------------------------------


async def test_server_close_with_net_error_mid_stream_raises_from_events() -> None:
    plan = ListenPlan(
        after_first_audio=["stt_results_interim.json"],
        close_after_first_audio=(1011, "NET-0001"),
    )
    async with FakeListen(plan).running() as fake:
        provider = fake.provider()
        async with provider.open_stream(sample_rate=16_000) as stream:
            await stream.send_audio(clip_chunks()[0])
            received: list[TranscriptEvent] = []

            async def read_all() -> None:
                async for event in stream.events():
                    received.append(event)

            with pytest.raises(ProviderUnavailableError, match="close code 1011 NET-0001"):
                await read_all()
            # Events that arrived before the failure were still delivered.
            assert [event.kind for event in received] == [K.INTERIM]
            # The socket is gone: sending more audio raises the same failure.
            with pytest.raises(ProviderUnavailableError, match="NET-0001"):
                await stream.send_audio(clip_chunks()[1])


async def test_undecodable_audio_close_is_a_provider_error() -> None:
    plan = ListenPlan(close_after_first_audio=(1008, "DATA-0000"))
    async with FakeListen(plan).running() as fake:
        with pytest.raises(ProviderError, match="1008 DATA-0000") as caught:
            await transcribe(fake.provider())
    assert not isinstance(caught.value, ProviderUnavailableError)


async def test_error_message_raises_from_events() -> None:
    plan = ListenPlan(after_first_audio=["stt_results_interim.json", "stt_error.json"])
    async with FakeListen(plan).running() as fake:
        with pytest.raises(ProviderError, match="SchemaError: Unknown field in message"):
            await transcribe(fake.provider())
        await asyncio.wait_for(fake.last.closed.wait(), 2)  # the adapter closed the socket


async def test_normal_close_before_finish_is_unexpected() -> None:
    plan = ListenPlan(close_after_first_audio=(1000, ""))
    async with FakeListen(plan).running() as fake:
        provider = fake.provider()
        async with provider.open_stream(sample_rate=16_000) as stream:
            await stream.send_audio(clip_chunks()[0])
            with pytest.raises(ProviderUnavailableError, match="closed early"):
                await collect(stream)


async def test_dropped_connection_after_finish_is_provider_unavailable() -> None:
    plan = ListenPlan(after_close_stream=["stt_results_final_part1.json"], ending="drop")
    async with FakeListen(plan).running() as fake:
        with pytest.raises(ProviderUnavailableError, match="no close frame"):
            await transcribe(fake.provider())


async def test_no_results_after_finish_times_out_as_unavailable() -> None:
    plan = ListenPlan(ending="silent")
    async with FakeListen(plan).running() as fake:
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(ProviderUnavailableError, match=r"within 0\.3s after finish"):
            await transcribe(fake.provider(timeout_seconds=0.3))
        elapsed = loop.time() - started
        await asyncio.wait_for(fake.last.closed.wait(), 2)

    assert 0.3 <= elapsed < 2.0


async def test_drain_timeout_also_applies_when_events_are_already_being_awaited() -> None:
    plan = ListenPlan(after_first_audio=["stt_results_interim.json"], ending="silent")
    async with FakeListen(plan).running() as fake:
        provider = fake.provider(timeout_seconds=0.3)
        async with provider.open_stream(sample_rate=16_000) as stream:
            reader = asyncio.create_task(collect(stream))
            await stream.send_audio(clip_chunks()[0])
            await asyncio.sleep(0.1)  # the background reader is now waiting on the socket
            await stream.finish()
            with pytest.raises(ProviderUnavailableError, match=r"within 0\.3s after finish"):
                await asyncio.wait_for(reader, 2)


# --- cancellation ------------------------------------------------------------------------------


async def test_cancellation_closes_the_socket_and_stops_background_tasks() -> None:
    plan = ListenPlan(after_first_audio=["stt_results_interim.json"], ending="silent")
    async with FakeListen(plan).running() as fake:
        provider = fake.provider(keepalive_seconds=0.05)
        opened = asyncio.Event()

        async def caller() -> None:
            async with provider.open_stream(sample_rate=16_000) as stream:
                await stream.send_audio(clip_chunks()[0])
                opened.set()
                await collect(stream)  # waits forever: the caller hangs up instead

        before = asyncio.all_tasks()
        task = asyncio.create_task(caller())
        await asyncio.wait_for(opened.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.wait_for(fake.last.closed.wait(), 2)
        leftovers = [
            t for t in asyncio.all_tasks() - before if t.get_name().startswith("deepgram-stt")
        ]
        assert leftovers == []
        assert "CloseStream" not in fake.last.control_types
