# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deepgram text-to-speech through the real httpx client with the network replaced.

``httpx.MockTransport`` answers with scripted responses: documented-shape error bodies from
``payloads/deepgram/`` and streamed raw PCM bodies.
"""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.integrations.errors import ProviderError, ProviderUnavailableError
from app.integrations.speech.deepgram_tts import DeepgramTextToSpeechProvider
from tests.contract.deepgram_fake import PAYLOADS, TEST_KEY

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]

REPLY = "Thanks, Ava. Could I have your date of birth, please?"


class TrackedStream(httpx.AsyncByteStream):
    """A response body delivered chunk by chunk; ``fail_with`` is raised after the chunks."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        fail_with: Exception | None = None,
        stall_after: float | None = None,
    ) -> None:
        self._chunks = chunks
        self._fail_with = fail_with
        self._stall_after = stall_after
        self.closed = False
        self.sent = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.sent += 1
            yield chunk
            await asyncio.sleep(0)
        if self._stall_after is not None:
            await asyncio.sleep(self._stall_after)
        if self._fail_with is not None:
            raise self._fail_with

    async def aclose(self) -> None:
        self.closed = True


def audio(stream: TrackedStream) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "audio/l16;rate=24000"}, stream=stream)


def error(status: int, fixture: str) -> httpx.Response:
    return httpx.Response(status, json=json.loads((PAYLOADS / fixture).read_text()))


Scripted = httpx.Response | Exception | float


class FakeSpeak:
    def __init__(self, *responses: Scripted) -> None:
        """Each item: a response, an exception raised by the transport, or a float: seconds to
        stall before answering with the next item."""
        self._queue: deque[Scripted] = deque(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._queue:
            raise AssertionError("FakeSpeak received more requests than scripted")
        item = self._queue.popleft()
        if isinstance(item, float):
            await asyncio.sleep(item)
            item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, httpx.Response)
        return item

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def provider(self, *, timeout_seconds: float = 2.0) -> DeepgramTextToSpeechProvider:
        return DeepgramTextToSpeechProvider(
            api_key=TEST_KEY,
            model="tts-test-model",
            timeout_seconds=timeout_seconds,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._handle)),
            sleep=self._sleep,
        )


async def synthesize(provider: DeepgramTextToSpeechProvider, text: str = REPLY) -> list[bytes]:
    return [chunk async for chunk in provider.synthesize(text)]


PCM = [bytes([n]) * 4_800 for n in range(1, 4)]  # three 100 ms chunks of 24 kHz linear16


# --- request and streaming ---------------------------------------------------------------------


async def test_request_shape_matches_the_documented_speak_call() -> None:
    fake = FakeSpeak(audio(TrackedStream(PCM)))
    await synthesize(fake.provider())

    (request,) = fake.requests
    assert request.method == "POST"
    assert request.url.scheme == "https"
    assert request.url.host == "api.deepgram.com"
    assert request.url.path == "/v1/speak"
    assert dict(request.url.params) == {
        "model": "tts-test-model",
        "encoding": "linear16",
        "sample_rate": "24000",
        "container": "none",
    }
    assert request.headers["authorization"] == f"Token {TEST_KEY}"
    assert request.headers["content-type"] == "application/json"
    assert TEST_KEY not in str(request.url)
    assert json.loads(request.content) == {"text": REPLY}


async def test_output_format_is_raw_24khz_mono_linear16() -> None:
    fmt = FakeSpeak().provider().output_format
    assert (fmt.sample_rate, fmt.channels, fmt.encoding) == (24_000, 1, "linear16")


async def test_streamed_chunks_pass_through_in_order_as_they_arrive() -> None:
    body = TrackedStream(PCM)
    fake = FakeSpeak(audio(body))
    provider = fake.provider()

    chunks = provider.synthesize(REPLY)
    first = await anext(chunks)
    assert first == PCM[0]
    assert body.sent == 1  # the first chunk is yielded before the rest of the body is read
    rest = [chunk async for chunk in chunks]

    assert [first, *rest] == PCM
    assert body.closed


async def test_chunks_hold_whole_samples_when_reads_split_a_sample() -> None:
    fake = FakeSpeak(audio(TrackedStream([b"\x01\x02\x03", b"\x04\x05\x06\x07\x08", b"\x09"])))
    chunks = await synthesize(fake.provider())

    assert chunks == [
        b"\x01\x02",
        b"\x03\x04\x05\x06\x07\x08",
    ]  # the trailing half sample is dropped
    assert all(len(chunk) % 2 == 0 for chunk in chunks)


async def test_consumer_stopping_early_releases_the_response() -> None:
    body = TrackedStream(PCM)
    fake = FakeSpeak(audio(body))
    chunks = fake.provider().synthesize(REPLY)

    await anext(chunks)
    await chunks.aclose()  # e.g. the caller barged in and playback stopped

    assert body.closed
    assert body.sent == 1


async def test_a_successful_response_without_audio_is_an_error() -> None:
    fake = FakeSpeak(audio(TrackedStream([])))
    with pytest.raises(ProviderError, match="no audio") as caught:
        await synthesize(fake.provider())
    assert not isinstance(caught.value, ProviderUnavailableError)


# --- failures ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "fixture", "code"),
    [(401, "tts_error_401.json", "INVALID_AUTH"), (400, "tts_error_400.json", "Bad Request")],
)
async def test_client_errors_are_not_retried(status: int, fixture: str, code: str) -> None:
    fake = FakeSpeak(error(status, fixture))
    with pytest.raises(ProviderError) as caught:
        await synthesize(fake.provider())

    assert not isinstance(caught.value, ProviderUnavailableError)
    assert caught.value.message == f"HTTP {status} {code}"
    assert TEST_KEY not in str(caught.value)
    assert len(fake.requests) == 1
    assert fake.sleeps == []


@pytest.mark.parametrize(
    "transient",
    [
        error(503, "tts_error_503.json"),
        httpx.Response(429),
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("read timed out"),
    ],
    ids=["503", "429", "connect-error", "read-timeout"],
)
async def test_transient_failure_before_audio_is_retried_once(transient: Scripted) -> None:
    fake = FakeSpeak(transient, audio(TrackedStream(PCM)))
    chunks = await synthesize(fake.provider())

    assert chunks == PCM
    assert len(fake.requests) == 2
    assert fake.sleeps == [0.25]


async def test_persistent_outage_is_unavailable_after_one_retry() -> None:
    fake = FakeSpeak(error(503, "tts_error_503.json"), error(503, "tts_error_503.json"))
    with pytest.raises(
        ProviderUnavailableError, match=r"2 attempts \(HTTP 503 SERVICE_UNAVAILABLE"
    ):
        await synthesize(fake.provider())
    assert len(fake.requests) == 2


async def test_failure_after_the_first_chunk_surfaces_without_retry() -> None:
    body = TrackedStream(PCM[:1], fail_with=httpx.ReadError("connection reset"))
    fake = FakeSpeak(audio(body), audio(TrackedStream(PCM)))
    received: list[bytes] = []

    async def play() -> None:
        async for chunk in fake.provider().synthesize(REPLY):
            received.append(chunk)

    with pytest.raises(ProviderUnavailableError, match=r"interrupted \(ReadError\)"):
        await play()

    assert received == PCM[:1]  # what was played stays played; nothing is repeated or padded
    assert len(fake.requests) == 1
    assert fake.sleeps == []
    assert body.closed


async def test_no_response_within_the_timeout_is_retried_then_unavailable() -> None:
    fake = FakeSpeak(1.0, 1.0)  # both attempts stall past the timeout
    with pytest.raises(ProviderUnavailableError, match=r"no response within 0\.1s"):
        await synthesize(fake.provider(timeout_seconds=0.1))
    assert len(fake.requests) == 2


async def test_body_stalling_after_audio_times_out_without_retry() -> None:
    body = TrackedStream(PCM[:1], stall_after=1.0)
    fake = FakeSpeak(audio(body))
    received: list[bytes] = []

    async def play() -> None:
        async for chunk in fake.provider(timeout_seconds=0.1).synthesize(REPLY):
            received.append(chunk)

    with pytest.raises(ProviderUnavailableError, match=r"no audio data within 0\.1s"):
        await play()
    assert received == PCM[:1]
    assert len(fake.requests) == 1


def test_error_bodies_are_documented_shape() -> None:
    for name in ("tts_error_400.json", "tts_error_401.json", "tts_error_503.json"):
        data: dict[str, Any] = json.loads((PAYLOADS / name).read_text())
        assert {"err_msg", "request_id"} <= data.keys()
        assert "err_code" in data or "error_code" in data
