# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deterministic speech mocks with the same streaming shape as the live providers (ADR-0005).

Mock speech-to-text does not understand speech. It recognises the committed scenario clips by a
hash of their first second of audio, which it actually receives over the stream, and replays
their transcript as a live provider would: interim results while audio arrives, then the text
split across two final segments, then an utterance-end signal. Unrecognised audio produces an
utterance end with no words.

Mock text-to-speech produces a soft tone whose length follows the reply, so playback, ordering
and cancellation are exercised without a voice.
"""

import asyncio
import hashlib
import math
import struct
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.integrations.speech.base import (
    AudioFormat,
    TranscriptEvent,
    TranscriptKind,
)
from app.voice.clips import ClipLibrary

_PREFIX_BYTES = 32_000  # one second of 16 kHz mono 16-bit audio
_INTERIM_STEPS = (0.3, 0.6, 0.85)


def _prefix_hash(pcm: bytes) -> str:
    return hashlib.sha256(pcm[:_PREFIX_BYTES]).hexdigest()


def _split_finals(text: str) -> list[str]:
    """Two final segments at a sentence or word boundary, as long utterances often arrive."""
    words = text.split()
    if len(words) < 4:
        return [text]
    cut = len(words) // 2
    for index, word in enumerate(words[: len(words) - 1]):
        if word.endswith((".", "?", "!", ",")) and index + 1 >= 2:
            cut = index + 1
            break
    return [" ".join(words[:cut]), " ".join(words[cut:])]


class _MockStream:
    def __init__(self, known: dict[str, tuple[str, int]]) -> None:
        self._known = known
        self._buffer = bytearray()
        self._received = 0
        self._transcript: str | None = None
        self._expected = 0
        self._sent_interims = 0
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()

    async def send_audio(self, chunk: bytes) -> None:
        self._received += len(chunk)
        if self._transcript is None and len(self._buffer) < _PREFIX_BYTES:
            self._buffer.extend(chunk)
            match = self._known.get(_prefix_hash(bytes(self._buffer)))
            if match is not None and len(self._buffer) >= min(_PREFIX_BYTES, match[1]):
                self._transcript, self._expected = match
        if self._transcript is None or not self._expected:
            return
        words = self._transcript.split()
        while self._sent_interims < len(_INTERIM_STEPS) and (
            self._received >= self._expected * _INTERIM_STEPS[self._sent_interims]
        ):
            shown = max(1, round(len(words) * _INTERIM_STEPS[self._sent_interims]))
            await self._queue.put(
                TranscriptEvent(TranscriptKind.INTERIM, " ".join(words[:shown]), confidence=0.6)
            )
            self._sent_interims += 1

    async def finish(self) -> None:
        if self._transcript is None:
            # Short clips are identified only once all their audio has arrived.
            match = self._known.get(_prefix_hash(bytes(self._buffer)))
            if match is not None and len(self._buffer) == match[1]:
                self._transcript = match[0]
        for segment in _split_finals(self._transcript) if self._transcript else []:
            await self._queue.put(TranscriptEvent(TranscriptKind.FINAL, segment, confidence=0.98))
        await self._queue.put(TranscriptEvent(TranscriptKind.UTTERANCE_END))
        await self._queue.put(None)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while (event := await self._queue.get()) is not None:
            yield event


class MockSpeechToTextProvider:
    name = "mock-stt"

    def __init__(self, library: ClipLibrary) -> None:
        self._known: dict[str, tuple[str, int]] = {}
        for clip_id in library.ids():
            clip = library.get(clip_id)
            pcm = clip.pcm()
            self._known[_prefix_hash(pcm)] = (clip.transcript, len(pcm))

    @asynccontextmanager
    async def open_stream(self, *, sample_rate: int) -> AsyncIterator[_MockStream]:
        yield _MockStream(self._known)


class MockTextToSpeechProvider:
    name = "mock-tts"
    output_format = AudioFormat(sample_rate=24_000)

    _MS_PER_WORD = 60
    _MAX_MS = 6_000
    _CHUNK_SAMPLES = 2_400  # 100 ms

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        rate = self.output_format.sample_rate
        total = min(self._MAX_MS, max(300, len(text.split()) * self._MS_PER_WORD)) * rate // 1000
        fade = rate // 50
        for start in range(0, total, self._CHUNK_SAMPLES):
            samples = []
            for n in range(start, min(total, start + self._CHUNK_SAMPLES)):
                envelope = min(1.0, n / fade, (total - n) / fade)
                value = 0.12 * envelope * math.sin(2 * math.pi * 440 * n / rate)
                samples.append(int(value * 32767))
            yield struct.pack(f"<{len(samples)}h", *samples)
            await asyncio.sleep(0)  # a streaming provider yields control between chunks
