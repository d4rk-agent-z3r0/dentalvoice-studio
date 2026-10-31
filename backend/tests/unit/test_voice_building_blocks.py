# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Utterance assembly, the clip library and the speech mocks."""

import shutil
import wave
from pathlib import Path

import pytest

from app.demo import catalog
from app.integrations.speech.base import TranscriptEvent, TranscriptKind
from app.integrations.speech.mock import MockSpeechToTextProvider, MockTextToSpeechProvider
from app.voice.assembler import UtteranceAssembler
from app.voice.clips import AUDIO_ROOT, CHUNK_BYTES, ClipLibrary, UnknownClipError, default_library

K = TranscriptKind


def interim(text: str) -> TranscriptEvent:
    return TranscriptEvent(K.INTERIM, text)


def final(text: str, *, speech_final: bool = False) -> TranscriptEvent:
    return TranscriptEvent(K.FINAL, text, speech_final=speech_final)


END = TranscriptEvent(K.UTTERANCE_END)


# --- assembler ---------------------------------------------------------------------------------


def test_interim_results_are_shown_but_never_committed() -> None:
    assembler = UtteranceAssembler()
    assert assembler.add(interim("my name")) is None
    assert assembler.pending == "my name"
    assert assembler.add(interim("my name is ava")) is None
    assert assembler.flush() is None  # no final arrived: nothing to commit


def test_multiple_finals_are_joined_in_order_and_none_are_lost() -> None:
    assembler = UtteranceAssembler()
    for event in [
        interim("next tuesday"),
        final("Next Tuesday would be great,"),
        interim("around ten"),
        final("around ten in the morning."),
    ]:
        assert assembler.add(event) is None
    assert assembler.pending == "Next Tuesday would be great, around ten in the morning."
    assert assembler.add(END) == "Next Tuesday would be great, around ten in the morning."
    assert assembler.add(END) is None  # the next utterance starts empty


def test_speech_final_completes_the_utterance() -> None:
    assembler = UtteranceAssembler()
    assembler.add(final("Hello."))
    assert assembler.add(final("I'm new.", speech_final=True)) == "Hello. I'm new."


def test_utterance_end_without_speech_is_not_an_utterance() -> None:
    assembler = UtteranceAssembler()
    assembler.add(interim("um"))
    assert assembler.add(END) is None
    assert assembler.add(final("   ")) is None
    assert assembler.add(END) is None


def test_stream_end_commits_collected_finals() -> None:
    assembler = UtteranceAssembler()
    assembler.add(final("Just call me."))
    assert assembler.flush() == "Just call me."


# --- clip library ------------------------------------------------------------------------------


def test_every_catalogue_clip_has_a_16khz_mono_fixture() -> None:
    library = default_library()
    assert library.ids() == sorted(catalog.clip_index())
    for clip_id in library.ids():
        clip = library.get(clip_id)
        assert clip.source == "espeak-fixture"
        assert len(clip.pcm()) > 0
        assert 500 < clip.duration_ms < 15_000


@pytest.mark.parametrize("clip_id", ["zz-99", "../fixtures/a-01", "a-01.wav", "", "manifest"])
def test_unknown_or_path_like_ids_are_refused(clip_id: str) -> None:
    with pytest.raises(UnknownClipError):
        default_library().get(clip_id)


def test_locally_generated_audio_is_preferred(tmp_path: Path) -> None:
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "local").mkdir()
    shutil.copy(AUDIO_ROOT / "fixtures" / "a-01.wav", tmp_path / "fixtures" / "a-01.wav")
    shutil.copy(AUDIO_ROOT / "fixtures" / "a-02.wav", tmp_path / "local" / "a-01.wav")
    library = ClipLibrary(tmp_path)

    assert library.get("a-01").source == "deepgram-local"
    with pytest.raises(UnknownClipError):
        library.get("a-02")  # in the catalogue, but no audio here


def test_wrong_audio_format_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "fixtures").mkdir()
    with wave.open(str(tmp_path / "fixtures" / "a-01.wav"), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\x00\x00" * 200)
    with pytest.raises(ValueError, match="16 kHz mono"):
        ClipLibrary(tmp_path).get("a-01").pcm()


# --- speech mocks ------------------------------------------------------------------------------


async def _transcribe(
    provider: MockSpeechToTextProvider, audio: bytes
) -> tuple[list[K], str | None]:
    kinds: list[K] = []
    committed: str | None = None
    assembler = UtteranceAssembler()
    async with provider.open_stream(sample_rate=16_000) as stream:
        for start in range(0, len(audio), CHUNK_BYTES):
            await stream.send_audio(audio[start : start + CHUNK_BYTES])
        await stream.finish()
        async for event in stream.events():
            kinds.append(event.kind)
            committed = assembler.add(event) or committed
    return kinds, committed


async def test_mock_stt_transcribes_every_fixture_exactly_with_interims_first() -> None:
    library = default_library()
    provider = MockSpeechToTextProvider(library)
    for clip_id in library.ids():
        clip = library.get(clip_id)
        kinds, committed = await _transcribe(provider, clip.pcm())
        assert committed == clip.transcript, clip_id
        assert kinds[0] is K.INTERIM
        assert kinds[-1] is K.UTTERANCE_END
        assert K.FINAL in kinds


async def test_mock_stt_does_not_invent_words_for_unknown_audio() -> None:
    provider = MockSpeechToTextProvider(default_library())
    kinds, committed = await _transcribe(provider, b"\x01\x02" * 40_000)
    assert (kinds, committed) == ([K.UTTERANCE_END], None)


async def test_mock_tts_streams_bounded_pcm_in_order() -> None:
    tts = MockTextToSpeechProvider()
    chunks = [chunk async for chunk in tts.synthesize("Hello! How may I help you today?")]
    total_ms = sum(len(c) for c in chunks) / 2 / tts.output_format.sample_rate * 1000
    assert len(chunks) > 1
    assert all(len(c) % 2 == 0 for c in chunks)
    assert 300 <= total_ms <= 6_000
    again = [chunk async for chunk in tts.synthesize("Hello! How may I help you today?")]
    assert again == chunks  # deterministic
