# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pure-ASGI middleware: refuse request bodies over a fixed size with ``413 PAYLOAD_TOO_LARGE``.

Every API request body is a small JSON document, so a large body can only be a mistake or an
attempt to exhaust memory. A declared ``Content-Length`` over the limit is refused before reading;
a body without one (chunked) is counted as it arrives and refused once it passes the limit.
"""

import json

import structlog
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 64 * 1024
TOO_LARGE_MESSAGE = f"The request body is larger than {MAX_BODY_BYTES} bytes."


def _response() -> tuple[Message, Message]:
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    body = json.dumps(
        {
            "error": {
                "code": "PAYLOAD_TOO_LARGE",
                "message": TOO_LARGE_MESSAGE,
                "request_id": request_id,
            }
        }
    ).encode()
    start: Message = {
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json"), (b"connection", b"close")],
    }
    return start, {"type": "http.response.body", "body": body}


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.max_bytes + 1
                if declared > self.max_bytes:
                    await self._refuse(send)
                    return

        received = 0

        async def counting_receive() -> Message:
            # An HTTPException passes through FastAPI's body parsing (other errors become a
            # generic 400) and is rendered by the app's handler in the standard error shape.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, TOO_LARGE_MESSAGE)
            return message

        await self.app(scope, counting_receive, send)

    async def _refuse(self, send: Send) -> None:
        start, body = _response()
        await send(start)
        await send(body)
