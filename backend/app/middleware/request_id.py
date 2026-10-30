# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Pure-ASGI request ID middleware (HTTP and WebSocket scopes).

Responsibilities:
- accept a well-formed incoming ``X-Request-ID`` or generate one;
- bind it to the logging context for the lifetime of the request/connection;
- return it on HTTP responses and on the WebSocket accept handshake;
- act as the last-resort error boundary for HTTP: an exception escaping the app is logged with its
  traceback and the request ID, and the client receives a generic 500 that carries the same ID.
"""

import json
import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

REQUEST_ID_HEADER = b"x-request-id"
# fullmatch semantics: '$' alone would accept a trailing newline (log/header injection).
_VALID_ID = re.compile(r"[A-Za-z0-9\-]{8,64}")
log = get_logger(__name__)

_INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
_INTERNAL_ERROR_MESSAGE = "Internal server error."


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER:
            candidate: str = value.decode("latin-1")
            return candidate if _VALID_ID.fullmatch(candidate) else None
    return None


def _internal_error_body(request_id: str) -> bytes:
    payload = {
        "error": {
            "code": _INTERNAL_ERROR_CODE,
            "message": _INTERNAL_ERROR_MESSAGE,
            "request_id": request_id,
        }
    }
    return json.dumps(payload).encode()


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        encoded_id = request_id.encode("latin-1")
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 0
        response_started = False

        async def send_with_header(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] in ("http.response.start", "websocket.accept"):
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, encoded_id))
                message["headers"] = headers
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception:
            # Error boundary, not silent swallowing: the traceback is logged with the request ID
            # and the client gets an explicit 500. Anything we cannot answer cleanly is re-raised.
            log.exception("unhandled_exception", method=scope.get("method"), path=scope.get("path"))
            if scope["type"] != "http" or response_started:
                raise
            status_code = 500
            body = _internal_error_body(request_id)
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (REQUEST_ID_HEADER, encoded_id),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            if scope["type"] == "http":
                log.info(
                    "http_request",
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            structlog.contextvars.clear_contextvars()
