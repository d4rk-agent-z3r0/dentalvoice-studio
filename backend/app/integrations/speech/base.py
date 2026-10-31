# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Provider-independent speech interfaces.

Speech-to-text is a stream: audio goes in as chunks and transcript events come out. Interim
events are for display only. Final events are committed text. An utterance is complete at an
utterance-end signal (or when the stream closes). Text-to-speech turns a reply into a stream of
audio chunks, so playback can start before synthesis finishes.

Implementations: Deepgram (live) and deterministic mocks. Provider types never leave their
modules.
"""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

# Every caller fixture is 16 kHz, mono, signed 16-bit little-endian PCM (linear16).
FIXTURE_SAMPLE_RATE = 16_000


class TranscriptKind(StrEnum):
    INTERIM = "interim"  # provisional; may change; never stored
    FINAL = "final"  # a finished segment of the utterance
    UTTERANCE_END = "utterance_end"  # the speaker has stopped (endpointing)


@dataclass(frozen=True)
class TranscriptEvent:
    kind: TranscriptKind
    text: str = ""
    speech_final: bool = False  # provider believes this final ends the utterance
    confidence: float | None = None


class SpeechStream(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...

    async def finish(self) -> None:
        """No more audio will be sent; the provider flushes its remaining results."""

    def events(self) -> AsyncIterator[TranscriptEvent]: ...


class SpeechToTextProvider(Protocol):
    name: str

    def open_stream(self, *, sample_rate: int) -> AbstractAsyncContextManager[SpeechStream]: ...


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int = 1
    encoding: str = "linear16"  # signed 16-bit little-endian PCM


class TextToSpeechProvider(Protocol):
    name: str
    output_format: AudioFormat

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw PCM chunks in ``output_format``. Raises ``ProviderError`` on failure."""
        ...
