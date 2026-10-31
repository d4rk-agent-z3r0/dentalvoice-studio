# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""A scripted stand-in for Deepgram's live listen endpoint: a real WebSocket server on loopback.

The adapter and the ``websockets`` client run unmodified against it; only the far end is fake.
It checks nothing itself; it records the handshake and every frame so tests can assert on them,
and plays back documented-shape messages from ``payloads/deepgram/``.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from app.integrations.speech.deepgram_stt import DeepgramSpeechToTextProvider

PAYLOADS = Path(__file__).parent / "payloads" / "deepgram"
TEST_KEY = "test-key-not-real"


def message(name: str) -> str:
    """A fixture as the exact JSON text Deepgram would send."""
    return (PAYLOADS / name).read_text()


# After CloseStream: close normally, stay silent (never answer), or drop the TCP connection.
Ending = Literal["close", "silent", "drop"]


@dataclass
class ListenPlan:
    reject_status: int | None = None  # refuse the handshake with this HTTP status
    reject_error: str = "Invalid credentials."  # sent as the dg-error header, as documented
    on_connect: list[str] = field(default_factory=list)  # fixtures sent right after the upgrade
    after_first_audio: list[str] = field(default_factory=list)
    after_close_stream: list[str] = field(default_factory=list)
    ending: Ending = "close"
    # Close the socket with (code, reason) right after the first audio frame and its messages.
    close_after_first_audio: tuple[int, str] | None = None


@dataclass
class Recorded:
    path: str = ""
    headers: Headers | None = None
    audio: bytearray = field(default_factory=bytearray)
    audio_frames: int = 0
    text_frames: list[str] = field(default_factory=list)
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)

    @property
    def control_types(self) -> list[str]:
        return [json.loads(text)["type"] for text in self.text_frames]


class FakeListen:
    def __init__(self, plan: ListenPlan | None = None) -> None:
        self.plan = plan or ListenPlan()
        self.connections: list[Recorded] = []
        self._server: Server | None = None

    @property
    def last(self) -> Recorded:
        return self.connections[-1]

    @property
    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.sockets[0].getsockname()[:2]
        return f"ws://{host}:{port}/v1/listen"

    def provider(
        self, *, timeout_seconds: float = 2.0, keepalive_seconds: float = 3.0
    ) -> DeepgramSpeechToTextProvider:
        return DeepgramSpeechToTextProvider(
            api_key=TEST_KEY,
            model="stt-test-model",
            timeout_seconds=timeout_seconds,
            base_url=self.url,
            keepalive_seconds=keepalive_seconds,
        )

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        self.connections.append(Recorded(path=request.path, headers=request.headers))
        if self.plan.reject_status is None:
            return None
        response = connection.respond(self.plan.reject_status, self.plan.reject_error + "\n")
        response.headers["dg-error"] = self.plan.reject_error
        return response

    async def _handle(self, connection: ServerConnection) -> None:
        record = self.last
        plan = self.plan
        closing: asyncio.Task[None] | None = None
        try:
            for name in plan.on_connect:
                await connection.send(message(name))
            async for frame in connection:
                if closing is not None:
                    continue  # like a real server: keep reading until the client's close reply
                if isinstance(frame, bytes):
                    record.audio.extend(frame)
                    record.audio_frames += 1
                    if record.audio_frames == 1:
                        for name in plan.after_first_audio:
                            await connection.send(message(name))
                        if plan.close_after_first_audio is not None:
                            code, reason = plan.close_after_first_audio
                            closing = asyncio.create_task(connection.close(code, reason))
                    continue
                record.text_frames.append(frame)
                if json.loads(frame).get("type") != "CloseStream":
                    continue
                for name in plan.after_close_stream:
                    await connection.send(message(name))
                if plan.ending == "close":
                    await connection.close()
                    return
                if plan.ending == "drop":
                    connection.transport.abort()
                    return
                # "silent": keep reading until the client gives up and closes.
        except ConnectionClosed:
            pass
        finally:
            if closing is not None:
                await closing
            record.closed.set()

    @asynccontextmanager
    async def running(self) -> AsyncIterator["FakeListen"]:
        async with serve(
            self._handle, "127.0.0.1", 0, process_request=self._process_request, compression=None
        ) as server:
            self._server = server
            yield self


@asynccontextmanager
async def unresponsive_server() -> AsyncIterator[str]:
    """Accepts TCP connections and never answers the WebSocket handshake."""
    held: list[asyncio.StreamWriter] = []

    async def hold(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        held.append(writer)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    try:
        host, port = server.sockets[0].getsockname()[:2]
        yield f"ws://{host}:{port}/v1/listen"
    finally:
        for writer in held:
            writer.close()
        server.close()
        await server.wait_closed()
