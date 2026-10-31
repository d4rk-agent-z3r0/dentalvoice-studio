# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Deepgram live (streaming) speech-to-text, behind ``SpeechToTextProvider``.

One WebSocket per caller utterance stream (``wss://api.deepgram.com/v1/listen``). Audio goes up as
binary frames of raw linear16 PCM. Deepgram's JSON messages come back and are read by a
background task into a queue, so a caller may send all audio first and read events afterwards,
or do both at once.

Message mapping (docs/providers.md lists the documented shapes this relies on):

- ``Results`` with ``is_final: false`` -> ``INTERIM``; with ``is_final: true`` -> ``FINAL``,
  carrying ``speech_final``. Text and confidence come from ``channel.alternatives[0]``.
- ``UtteranceEnd`` -> ``UTTERANCE_END``, except ``last_word_end == -1``, which Deepgram documents as
  "already finalized, ignore".
- ``Metadata``, ``SpeechStarted`` and any other informational message: ignored.
- ``Error`` message: ``ProviderError`` raised from ``events()``.

``finish()`` sends ``{"type": "CloseStream"}``: Deepgram then processes the remaining audio, sends
the last results and ``Metadata``, and closes the socket. ``events()`` ends at that close. If the
close has not happened within ``timeout_seconds`` of ``finish()``, ``events()`` raises
``ProviderUnavailableError``. While no audio is being sent, ``{"type": "KeepAlive"}`` is sent every
``keepalive_seconds`` (Deepgram closes an idle stream after about 10 seconds).

Failure policy:

- Handshake refused with HTTP 401/403/400 or another 4xx: ``ProviderError`` (502). Retrying would
  not help: the key, the model id or a parameter is wrong.
- Handshake HTTP 429 or 5xx, connection refused or reset, handshake timeout:
  ``ProviderUnavailableError`` (503).
- Mid-stream: an unexpected close or close code 1011 (``NET-*``) -> ``ProviderUnavailableError``;
  close code 1008 (``DATA-0000``, undecodable audio) -> ``ProviderError``. Raised from ``events()``
  (and from ``send_audio``/``finish`` once the socket is gone). Never swallowed, never replaced
  by a mock (ADR-0005).

Leaving the ``open_stream`` context (normally, on error or by cancellation when the caller hangs
up) stops the background tasks and closes the socket. The API key travels only in the
``Authorization`` header. Transcripts and the key are never logged; the ``websockets`` library logs
through a private logger that never emits DEBUG, because its debug output includes request headers
and frame contents. ``websockets`` types never leave this module.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException
from websockets.frames import CloseCode

from app.core.logging import get_logger
from app.integrations.errors import ProviderError, ProviderUnavailableError
from app.integrations.speech.base import TranscriptEvent, TranscriptKind

log = get_logger(__name__)

PROVIDER = "deepgram-stt"
DEFAULT_LISTEN_URL = "wss://api.deepgram.com/v1/listen"

_KEEPALIVE = json.dumps({"type": "KeepAlive"})
_CLOSE_STREAM = json.dumps({"type": "CloseStream"})
_CLOSE_SECONDS = 2.0  # bound on our own close handshake, so a hang-up never waits long

# The library's debug log prints handshake headers (including Authorization) and frames (which
# carry transcripts). It gets a logger of its own that is pinned above DEBUG.
_LIBRARY_LOG = logging.getLogger("app.integrations.speech.deepgram_stt.websockets")
_LIBRARY_LOG.setLevel(logging.WARNING)


class _StreamEnd:
    """Queue sentinel: the socket closed after ``finish()`` as documented."""


_END = _StreamEnd()
_QueueItem = TranscriptEvent | ProviderError | _StreamEnd


class DeepgramSpeechToTextProvider:
    name = PROVIDER

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = DEFAULT_LISTEN_URL,
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
        keepalive_seconds: float = 3.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._base_url = base_url
        self._endpointing_ms = endpointing_ms
        self._utterance_end_ms = utterance_end_ms
        self._keepalive = keepalive_seconds

    def stream_url(self, *, sample_rate: int) -> str:
        """The listen URL with its query string. It never contains the API key."""
        query = {
            "model": self._model,
            "encoding": "linear16",
            "sample_rate": str(sample_rate),
            "channels": "1",
            "interim_results": "true",
            "endpointing": str(self._endpointing_ms),
            "utterance_end_ms": str(self._utterance_end_ms),
            "vad_events": "true",
            "smart_format": "true",
            "punctuate": "true",
        }
        return f"{self._base_url}?{urlencode(query)}"

    @asynccontextmanager
    async def open_stream(self, *, sample_rate: int) -> AsyncIterator["DeepgramSpeechStream"]:
        connection = await self._connect(self.stream_url(sample_rate=sample_rate))
        stream = DeepgramSpeechStream(
            connection, timeout_seconds=self._timeout, keepalive_seconds=self._keepalive
        )
        try:
            yield stream
        finally:
            await stream.aclose()

    async def _connect(self, url: str) -> ClientConnection:
        try:
            return await connect(
                url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=self._timeout,
                close_timeout=_CLOSE_SECONDS,
                compression=None,  # audio does not compress; keep latency predictable
                logger=_LIBRARY_LOG,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            reason = _handshake_reason(error)
            log.warning("stt_handshake_rejected", provider=PROVIDER, status=status)
            if status == 429 or status >= 500:
                raise ProviderUnavailableError(PROVIDER, f"HTTP {status}{reason}") from error
            raise ProviderError(PROVIDER, f"HTTP {status}{reason}") from error
        except TimeoutError as error:
            raise ProviderUnavailableError(
                PROVIDER, f"connection timed out after {self._timeout:g}s"
            ) from error
        except (OSError, WebSocketException) as error:
            log.warning("stt_connect_failed", provider=PROVIDER, error=type(error).__name__)
            raise ProviderUnavailableError(
                PROVIDER, f"connection failed ({type(error).__name__})"
            ) from error


class DeepgramSpeechStream:
    """One open Deepgram stream. Created by ``DeepgramSpeechToTextProvider.open_stream``."""

    def __init__(
        self, connection: ClientConnection, *, timeout_seconds: float, keepalive_seconds: float
    ) -> None:
        self._connection = connection
        self._timeout = timeout_seconds
        self._keepalive_seconds = keepalive_seconds
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._failure: ProviderError | None = None
        self._terminal = False  # an end or an error is queued
        self._finished = False
        self._loop = asyncio.get_running_loop()
        self._last_sent = self._loop.time()
        self._drain_deadline: asyncio.Timeout | None = None
        self._reader = asyncio.create_task(self._read(), name="deepgram-stt-reader")
        self._keeper = asyncio.create_task(self._keep_alive(), name="deepgram-stt-keepalive")

    async def send_audio(self, chunk: bytes) -> None:
        if self._finished:
            raise RuntimeError("send_audio() after finish()")
        if not chunk:
            return  # Deepgram documents that empty frames can close the stream
        await self._send(chunk)

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._keeper.cancel()
        await self._send(_CLOSE_STREAM)
        if self._drain_deadline is not None:
            self._drain_deadline.reschedule(self._loop.time() + self._timeout)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            item = await self._queue.get()
            if isinstance(item, _StreamEnd):
                self._queue.put_nowait(item)  # later calls end immediately too
                return
            if isinstance(item, ProviderError):
                self._queue.put_nowait(item)
                raise item
            yield item

    async def aclose(self) -> None:
        self._finished = True
        for task in (self._keeper, self._reader):
            task.cancel()
        for task in (self._keeper, self._reader):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if not self._terminal:
            # Closed by its owner (for example on hang-up): a reader still iterating ends.
            self._end()
        # Bounded by close_timeout. A socket the peer already closed returns at once.
        await self._connection.close()

    async def _send(self, message: bytes | str) -> None:
        try:
            await self._connection.send(message)
        except ConnectionClosed as error:
            # The reader records why the socket closed; wait briefly for it so the caller sees
            # the real reason rather than a generic one. (``wait`` neither raises the reader's
            # outcome nor hides a cancellation of the caller.)
            await asyncio.wait({self._reader}, timeout=_CLOSE_SECONDS)
            raise self._failure or _close_error(error, finished=False) from error
        self._last_sent = self._loop.time()

    async def _read(self) -> None:
        try:
            async with asyncio.timeout(None) as deadline:
                self._drain_deadline = deadline
                if self._finished:  # finish() ran before this task started
                    deadline.reschedule(self._loop.time() + self._timeout)
                async for message in self._connection:
                    event = _parse(message)
                    if event is not None:
                        self._queue.put_nowait(event)
        except _UpstreamError as error:
            self._fail(error.error)
            await self._connection.close()
        except TimeoutError:
            self._fail(
                ProviderUnavailableError(
                    PROVIDER, f"no end of results within {self._timeout:g}s after finish"
                )
            )
            await self._connection.close()
        except ConnectionClosed as error:
            self._fail(_close_error(error, finished=self._finished))
        else:
            # ``async for`` ends silently on a normal (1000/1001) close.
            if self._finished:
                self._end()
            else:
                code = self._connection.close_code
                self._fail(
                    ProviderUnavailableError(PROVIDER, f"stream closed early (close code {code})")
                )

    def _fail(self, error: ProviderError) -> None:
        self._failure = error
        self._terminal = True
        log.warning("stt_stream_failed", provider=PROVIDER, error_code=error.code)
        self._queue.put_nowait(error)

    def _end(self) -> None:
        self._terminal = True
        self._queue.put_nowait(_END)

    async def _keep_alive(self) -> None:
        while True:
            await asyncio.sleep(self._keepalive_seconds)
            idle = self._loop.time() - self._last_sent
            if idle >= self._keepalive_seconds:
                try:
                    await self._connection.send(_KEEPALIVE)
                except ConnectionClosed:
                    return  # the reader reports the close
                self._last_sent = self._loop.time()


class _UpstreamError(Exception):
    def __init__(self, error: ProviderError) -> None:
        super().__init__(error.message)
        self.error = error


def _parse(message: str | bytes) -> TranscriptEvent | None:
    if isinstance(message, bytes):
        raise _UpstreamError(ProviderError(PROVIDER, "unexpected binary message"))
    try:
        data: Any = json.loads(message)
    except ValueError as error:
        raise _UpstreamError(ProviderError(PROVIDER, "unparseable message")) from error
    if not isinstance(data, dict):
        raise _UpstreamError(ProviderError(PROVIDER, "unexpected message shape"))
    kind = data.get("type")
    if kind == "Results":
        return _result(data)
    if kind == "UtteranceEnd":
        if data.get("last_word_end") == -1:
            return None  # documented: the utterance was already finalized; ignore
        return TranscriptEvent(TranscriptKind.UTTERANCE_END)
    if kind == "Error":
        variant = _short(data.get("variant"))
        description = _short(data.get("description") or data.get("message"))
        raise _UpstreamError(ProviderError(PROVIDER, f"error message: {variant}: {description}"))
    return None  # Metadata, SpeechStarted, and anything informational


def _result(data: dict[str, Any]) -> TranscriptEvent:
    try:
        alternative = data["channel"]["alternatives"][0]
        text = alternative["transcript"]
        if not isinstance(text, str):
            raise TypeError("transcript")
        confidence = alternative.get("confidence")
        is_final = data.get("is_final") is True
        speech_final = data.get("speech_final") is True
    except (KeyError, IndexError, TypeError) as error:
        raise _UpstreamError(ProviderError(PROVIDER, "malformed Results message")) from error
    return TranscriptEvent(
        TranscriptKind.FINAL if is_final else TranscriptKind.INTERIM,
        text=text,
        speech_final=is_final and speech_final,
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
    )


def _close_error(error: ConnectionClosed, *, finished: bool) -> ProviderError:
    close = error.rcvd
    if close is None:
        return ProviderUnavailableError(PROVIDER, "connection lost (no close frame)")
    detail = f"close code {close.code}" + (f" {_short(close.reason)}" if close.reason else "")
    if close.code == CloseCode.POLICY_VIOLATION:  # 1008 DATA-0000: audio could not be decoded
        return ProviderError(PROVIDER, f"stream rejected: {detail}")
    if close.code == CloseCode.NORMAL_CLOSURE and not finished:
        return ProviderUnavailableError(PROVIDER, f"stream closed early: {detail}")
    return ProviderUnavailableError(PROVIDER, f"stream closed: {detail}")


def _handshake_reason(error: InvalidStatus) -> str:
    reason = error.response.headers.get("dg-error")
    return f" ({_short(reason)})" if reason else ""


def _short(value: object, limit: int = 160) -> str:
    text = str(value) if value is not None else "unknown"
    return text if len(text) <= limit else text[: limit - 1] + "…"
