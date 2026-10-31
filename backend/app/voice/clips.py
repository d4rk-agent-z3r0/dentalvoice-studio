# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The allow-listed library of synthetic caller clips.

Only clip ids from the scenario catalogue exist. A clip resolves to a locally generated
(Deepgram) file when present, otherwise to the committed eSpeak NG fixture. No path ever comes
from a request, so traversal is impossible: ids are looked up, not joined.
"""

import wave
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.demo import catalog
from app.integrations.speech.base import FIXTURE_SAMPLE_RATE

AUDIO_ROOT = Path(__file__).resolve().parents[2] / "demo_data" / "audio"
# 20 ms of 16 kHz mono 16-bit audio: the chunk size streamed to speech-to-text.
CHUNK_BYTES = FIXTURE_SAMPLE_RATE * 2 // 50


class UnknownClipError(LookupError):
    pass


@dataclass(frozen=True)
class Clip:
    id: str
    transcript: str
    path: Path
    source: str  # "deepgram-local" or "espeak-fixture"

    def pcm(self) -> bytes:
        """Raw linear16 samples (the WAV payload without its header)."""
        with wave.open(str(self.path), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (
                FIXTURE_SAMPLE_RATE,
                1,
                2,
            ):
                raise ValueError(f"{self.id}: fixture is not 16 kHz mono 16-bit PCM")
            return audio.readframes(audio.getnframes())

    def chunks(self) -> Iterator[bytes]:
        data = self.pcm()
        for start in range(0, len(data), CHUNK_BYTES):
            yield data[start : start + CHUNK_BYTES]

    @property
    def duration_ms(self) -> int:
        with wave.open(str(self.path), "rb") as audio:
            return round(audio.getnframes() * 1000 / audio.getframerate())


class ClipLibrary:
    def __init__(self, root: Path = AUDIO_ROOT) -> None:
        self._root = root
        self._catalogue = catalog.clip_index()

    def get(self, clip_id: str) -> Clip:
        spec = self._catalogue.get(clip_id)
        if spec is None:
            raise UnknownClipError(clip_id)
        local = self._root / "local" / f"{clip_id}.wav"
        if local.is_file():
            return Clip(clip_id, spec.transcript, local, "deepgram-local")
        fixture = self._root / "fixtures" / f"{clip_id}.wav"
        if not fixture.is_file():
            raise UnknownClipError(clip_id)
        return Clip(clip_id, spec.transcript, fixture, "espeak-fixture")

    def ids(self) -> list[str]:
        return sorted(self._catalogue)


@cache
def default_library() -> ClipLibrary:
    return ClipLibrary()
