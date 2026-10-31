# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""One live voice connection: synthetic caller audio in, receptionist speech out.

The client never sends audio. It sends commands (``start``, ``next_clip``, ``end``). For
``next_clip`` the *server* picks the scenario's next fixture, tells the browser to play it, and
streams the same file to speech-to-text (ADR-0002). All speech-to-text input therefore comes from
predefined synthetic fixtures.

Per caller turn:

1. stream the clip to STT; forward interim text for display; assemble finals into one utterance;
2. hand the utterance to the conversation orchestrator (validation, state, persistence);
3. stream the reply's speech as binary frames prefixed with the 4-byte big-endian turn number,
   so the client drops audio of a turn it has moved past;
4. report measured latencies: STT (end of caller audio → utterance), LLM, TTS first byte, total
   (end of caller audio → first reply audio). Measured here, never estimated.

Barge-in: ``next_clip`` while the receptionist is still speaking cancels that speech. ``end``
cancels anything in flight. A provider failure is reported to the client as an error and nothing
is substituted (ADR-0005). Transcript text is never logged.
"""

import asyncio
import struct
import time
import uuid
from collections.abc import AsyncIterable, Callable
from typing import Any, Protocol

from app.core.logging import get_logger
from app.domain.enums import TERMINAL_STATES, ConversationState
from app.domain.errors import DomainError
from app.integrations.errors import ProviderError
from app.integrations.speech.base import (
    FIXTURE_SAMPLE_RATE,
    SpeechToTextProvider,
    TextToSpeechProvider,
    TranscriptKind,
)
from app.orchestrators.conversation import ConversationOrchestrator, TurnResult
from app.services.conversations import ConversationService
from app.voice.assembler import UtteranceAssembler
from app.voice.clips import ClipLibrary

log = get_logger(__name__)

CLIP_URL = "/api/v1/audio/clips/{clip_id}"
_FRAME_SECONDS = 0.02  # each fixture chunk is 20 ms of audio


class Outbound(Protocol):
    async def send_json(self, data: dict[str, Any]) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...


def audio_frame(turn_seq: int, pcm: bytes) -> bytes:
    return struct.pack(">I", turn_seq) + pcm


class VoiceSession:
    def __init__(
        self,
        *,
        clinic_id: uuid.UUID,
        conversation_id: uuid.UUID,
        orchestrator: ConversationOrchestrator,
        conversations: ConversationService,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        library: ClipLibrary,
        out: Outbound,
        realtime_factor: float = 1.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._clinic_id = clinic_id
        self._conversation_id = conversation_id
        self._orchestrator = orchestrator
        self._conversations = conversations
        self._stt = stt
        self._tts = tts
        self._library = library
        self._out = out
        self._realtime = realtime_factor
        self._clock = clock
        self._speaking = False
        self._closed = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    # --- command loop ---------------------------------------------------------------------------

    async def run(self, commands: AsyncIterable[dict[str, Any]]) -> None:
        """Process commands until the client leaves or the call ends."""
        progress = await self._conversations.voice_progress(self._clinic_id, self._conversation_id)
        await self._send(
            "ready",
            state=progress.state.value,
            audio={
                "sample_rate": self._tts.output_format.sample_rate,
                "encoding": self._tts.output_format.encoding,
                "channels": self._tts.output_format.channels,
            },
        )
        reader = aiter(commands)
        current: asyncio.Task[None] | None = None
        pending: str | None = None  # one follow-up command may wait for the running turn
        next_command: asyncio.Future[dict[str, Any]] | None = None
        ended = asyncio.ensure_future(self._closed.wait())
        try:
            while not self.closed:
                if next_command is None:
                    next_command = asyncio.ensure_future(anext(reader))
                waiting: set[asyncio.Future[Any]] = {next_command, ended}
                if current is not None and not current.done():
                    waiting.add(current)
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if ended in done:
                    break  # the call reached a terminal state
                if current is not None and current in done:
                    _reap(current)
                    current = None
                    if pending is not None:
                        current, pending = asyncio.create_task(self._handle(pending)), None
                if next_command not in done:
                    continue
                try:
                    command = next_command.result()
                except StopAsyncIteration:
                    break  # the client went away
                next_command = None
                kind = command.get("type")
                if kind == "end":
                    await _cancel(current)
                    await self._end()
                    break
                if kind not in ("start", "next_clip"):
                    await self._error("INVALID_MESSAGE", "Unknown command.")
                elif current is None or current.done():
                    current = asyncio.create_task(self._handle(kind))
                elif kind == "next_clip" and self._speaking:
                    await _cancel(current)  # barge-in: stop the receptionist speaking
                    current, pending = asyncio.create_task(self._handle(kind)), None
                elif pending is None:
                    pending = kind  # runs as soon as the current turn has finished
                else:
                    await self._error("BUSY", "The previous turn is still being processed.")
        finally:
            await _cancel(next_command)
            await _cancel(ended)
            await _cancel(current)
            _reap(current)

    async def _handle(self, kind: str) -> None:
        try:
            if kind == "start":
                await self._start()
            else:
                await self._caller_turn()
        except ProviderError as error:
            await self._error(error.code, "A speech or language provider failed.", error.provider)
        except DomainError as error:
            await self._error(error.code, error.message)

    # --- turns -----------------------------------------------------------------------------------

    async def _start(self) -> None:
        result = await self._orchestrator.start(self._clinic_id, self._conversation_id)
        await self._report_turn(result)
        await self._speak(result, audio_end_at=None, stt_ms=None)

    async def _caller_turn(self) -> None:
        progress = await self._conversations.voice_progress(self._clinic_id, self._conversation_id)
        if progress.state in TERMINAL_STATES:
            await self._error("CONVERSATION_CLOSED", "This conversation has ended.")
            return
        if progress.state is ConversationState.CREATED:
            await self._error("INVALID_STATE_TRANSITION", "Start the conversation first.")
            return
        clip_id = progress.next_clip
        if clip_id is None:
            await self._error("NO_MORE_CLIPS", "This scenario has no more caller clips.")
            return
        clip = self._library.get(clip_id)
        await self._send(
            "clip",
            clip_id=clip.id,
            url=CLIP_URL.format(clip_id=clip.id),
            duration_ms=clip.duration_ms,
        )

        assembler = UtteranceAssembler()
        utterance: str | None = None
        audio_end_at = 0.0
        completed_at = 0.0
        async with self._stt.open_stream(sample_rate=FIXTURE_SAMPLE_RATE) as stream:

            async def pump() -> None:
                nonlocal audio_end_at
                for chunk in clip.chunks():
                    await stream.send_audio(chunk)
                    if self._realtime > 0:
                        await asyncio.sleep(_FRAME_SECONDS * self._realtime)
                audio_end_at = self._clock()
                await stream.finish()

            pumping = asyncio.create_task(pump())
            try:
                async for event in stream.events():
                    done = assembler.add(event)
                    if event.kind is TranscriptKind.INTERIM or (
                        event.kind is TranscriptKind.FINAL and done is None
                    ):
                        await self._send("transcript.interim", text=assembler.pending)
                    if done is not None:
                        utterance, completed_at = done, self._clock()
                        break
                await pumping
            finally:
                await _cancel(pumping)
        if utterance is None:
            utterance = assembler.flush()
            completed_at = self._clock()
        if utterance is None:
            await self._error("NO_SPEECH", "No speech was recognised in that clip.")
            return

        stt_ms = max(0, round((completed_at - audio_end_at) * 1000))
        result = await self._orchestrator.handle_caller_turn(
            self._clinic_id, self._conversation_id, utterance, clip_id=clip.id, stt_ms=stt_ms
        )
        await self._send("utterance.final", turn_seq=result.caller_turn_seq, text=utterance)
        await self._report_turn(result)
        await self._speak(result, audio_end_at=audio_end_at, stt_ms=stt_ms)

    async def _report_turn(self, result: TurnResult) -> None:
        if result.path:
            await self._send(
                "state",
                state=result.state.value,
                previous=result.previous_state.value,
                path=[s.value for s in result.path],
            )
        await self._send("assistant.text", turn_seq=result.receptionist_turn_seq, text=result.reply)
        await self._send(
            "intake",
            missing_fields=[f.value for f in result.missing_fields],
            rejected_fields={f.value: reason for f, reason in result.rejected_fields.items()},
            corrected_fields=[f.value for f in result.corrected_fields],
        )

    async def _speak(
        self, result: TurnResult, *, audio_end_at: float | None, stt_ms: int | None
    ) -> None:
        turn_seq = result.receptionist_turn_seq
        started = self._clock()
        first_byte_at: float | None = None
        self._speaking = True
        try:
            async for chunk in self._tts.synthesize(result.reply):
                if first_byte_at is None:
                    first_byte_at = self._clock()
                await self._out.send_bytes(audio_frame(turn_seq, chunk))
            await self._send("assistant.audio_end", turn_seq=turn_seq)
        except asyncio.CancelledError:
            await self._send_quietly("assistant.audio_cancelled", turn_seq=turn_seq)
            raise
        finally:
            self._speaking = False
            tts_ms = round((first_byte_at - started) * 1000) if first_byte_at else None
            total_ms = (
                round((first_byte_at - audio_end_at) * 1000)
                if first_byte_at is not None and audio_end_at is not None
                else None
            )
            await self._send_quietly(
                "latency",
                turn_seq=turn_seq,
                stt_ms=stt_ms,
                llm_ms=result.llm_ms,
                tts_first_byte_ms=tts_ms,
                total_ms=total_ms,
            )
            await asyncio.shield(
                self._orchestrator.record_reply_audio(
                    self._clinic_id,
                    self._conversation_id,
                    turn_seq,
                    tts_ms=tts_ms,
                    total_ms=total_ms,
                )
            )
        if result.state in TERMINAL_STATES:
            await self._send("closed", state=result.state.value)
            self._closed.set()

    async def _end(self) -> None:
        progress = await self._conversations.voice_progress(self._clinic_id, self._conversation_id)
        final_state = progress.state
        if progress.state not in TERMINAL_STATES:
            final_state = await self._orchestrator.end(self._clinic_id, self._conversation_id)
            await self._send(
                "state",
                state=final_state.value,
                previous=progress.state.value,
                path=[final_state.value],
            )
        await self._send("closed", state=final_state.value)
        self._closed.set()

    # --- messages ----------------------------------------------------------------------------

    async def _send(self, type_: str, **payload: Any) -> None:
        await self._out.send_json({"type": type_, **payload})

    async def _send_quietly(self, type_: str, **payload: Any) -> None:
        """For cleanup paths: the client may already be gone."""
        try:
            await self._send(type_, **payload)
        except Exception:  # a closed socket must not mask the original outcome
            log.debug("voice_send_after_close", type=type_)

    async def _error(self, code: str, message: str, provider: str | None = None) -> None:
        log.warning(
            "voice_session_error",
            conversation_id=str(self._conversation_id),
            code=code,
            provider=provider,
        )
        body: dict[str, Any] = {"code": code, "message": message}
        if provider is not None:
            body["provider"] = provider
        await self._send("error", **body)


def _reap(task: "asyncio.Future[Any] | None") -> None:
    """Retrieve a finished task's exception so it is logged, not silently dropped."""
    if task is not None and task.done() and not task.cancelled():
        error = task.exception()
        if error is not None:
            log.error("voice_turn_failed", error=type(error).__name__)


async def _cancel(task: "asyncio.Future[Any] | None") -> None:
    if task is None or task.done():
        return
    task.cancel()
    # gather() absorbs the task's own CancelledError but still propagates a cancellation of the
    # caller, so cancelling a child never swallows our own shutdown.
    await asyncio.gather(task, return_exceptions=True)
