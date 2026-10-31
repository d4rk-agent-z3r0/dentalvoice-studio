# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Run the real ASGI app under uvicorn on a free local port, and talk to it over WebSocket."""

import asyncio
import json
import socket
import struct
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import uvicorn
import websockets
from fastapi import FastAPI


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@asynccontextmanager
async def live_server(app: FastAPI) -> AsyncIterator[str]:
    """Yields the base URL (``http://127.0.0.1:<port>``) while uvicorn serves ``app``."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@dataclass
class Transcript:
    """Everything a client received, in order."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    frames: list[tuple[int, int]] = field(default_factory=list)  # (turn_seq, pcm bytes)

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == type_]


class VoiceClient:
    def __init__(self, connection: websockets.ClientConnection) -> None:
        self.connection = connection
        self.received = Transcript()

    async def send(self, type_: str) -> None:
        await self.connection.send(json.dumps({"type": type_}))

    async def until(
        self, predicate: Callable[[dict[str, Any]], bool], limit_s: float = 15.0
    ) -> dict[str, Any]:
        """Read until a JSON message matches ``predicate``; binary frames are recorded."""
        async with asyncio.timeout(limit_s):
            while True:
                raw = await self.connection.recv()
                if isinstance(raw, bytes):
                    (turn_seq,) = struct.unpack(">I", raw[:4])
                    self.received.frames.append((turn_seq, len(raw) - 4))
                    continue
                message: dict[str, Any] = json.loads(raw)
                self.received.messages.append(message)
                if predicate(message):
                    return message

    async def turn_done(self) -> dict[str, Any]:
        """A turn ends with its latency report. An error first fails the test."""
        message = await self.until(lambda m: m["type"] in ("latency", "error"))
        if message["type"] == "error":
            raise AssertionError(f"voice error: {message}")
        return message


def ws_url(base: str, conversation_id: str, ticket: str) -> str:
    return (
        f"{base.replace('http', 'ws', 1)}/api/v1/ws/conversations/{conversation_id}?ticket={ticket}"
    )
