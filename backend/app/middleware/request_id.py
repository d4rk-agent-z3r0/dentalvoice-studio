"""Pure-ASGI request ID middleware (works for HTTP and WebSocket scopes)."""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

REQUEST_ID_HEADER = b"x-request-id"
_VALID_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
log = get_logger(__name__)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER:
            candidate = value.decode("latin-1")
            # Only accept well-formed IDs to avoid log injection.
            return candidate if _VALID_ID.match(candidate) else None
    return None


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 0

        async def send_with_header(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
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
