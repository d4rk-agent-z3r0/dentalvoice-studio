# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import json
import uuid

import httpx
import pytest
from fastapi import FastAPI, WebSocket

from app.core.config import Settings
from app.core.logging import get_logger
from app.main import create_app
from app.middleware.request_id import _incoming_request_id
from tests.conftest import ClientFactory


def _json_lines(text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def _app_with_test_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    async def boom() -> None:
        raise RuntimeError("kaboom")

    async def echo_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    app.add_api_route("/test/boom", boom)
    app.add_api_websocket_route("/test/ws", echo_socket)
    return app


async def test_generates_request_id_when_absent(
    client_factory: ClientFactory, offline_settings: Settings
) -> None:
    async with client_factory(offline_settings) as client:
        response = await client.get("/health/live")

    uuid.UUID(response.headers["x-request-id"])  # raises if not a UUID


async def test_echoes_well_formed_incoming_request_id(
    client_factory: ClientFactory, offline_settings: Settings
) -> None:
    async with client_factory(offline_settings) as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "abc-12345678"})

    assert response.headers["x-request-id"] == "abc-12345678"


async def test_replaces_malformed_incoming_request_id(
    client_factory: ClientFactory, offline_settings: Settings
) -> None:
    async with client_factory(offline_settings) as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "bad id with space"})

    returned = response.headers["x-request-id"]
    assert returned != "bad id with space"
    uuid.UUID(returned)


@pytest.mark.parametrize("raw", [b"abcdefgh\n", b"abcdefgh\r\nX-Evil: 1", b"short", b"a" * 65])
def test_rejects_ids_that_are_not_fully_well_formed(raw: bytes) -> None:
    scope = {"type": "http", "headers": [(b"x-request-id", raw)]}
    assert _incoming_request_id(scope) is None


async def test_unhandled_exception_returns_safe_500_with_request_id(
    offline_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    app = _app_with_test_routes(offline_settings)
    # raise_app_exceptions stays True: if the exception escaped the middleware, the test errors.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test/boom", headers={"X-Request-ID": "req-boom-0001"})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-boom-0001"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error.",
            "request_id": "req-boom-0001",
        }
    }
    assert "kaboom" not in response.text

    logs = _json_lines(capsys.readouterr().out)
    error = next(line for line in logs if line["event"] == "unhandled_exception")
    assert error["level"] == "error"
    assert error["request_id"] == "req-boom-0001"
    assert "RuntimeError: kaboom" in str(error["exception"])
    access = next(line for line in logs if line["event"] == "http_request")
    assert access["status"] == 500


async def test_websocket_accept_carries_request_id(offline_settings: Settings) -> None:
    app = _app_with_test_routes(offline_settings)
    inbound: list[dict[str, object]] = [{"type": "websocket.connect"}]
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return inbound.pop(0) if inbound else {"type": "websocket.disconnect", "code": 1000}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/test/ws",
        "raw_path": b"/test/ws",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test"), (b"x-request-id", b"ws-req-00001")],
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
        "subprotocols": [],
    }
    await app(scope, receive, send)  # type: ignore[arg-type]

    accept = next(m for m in sent if m["type"] == "websocket.accept")
    assert (b"x-request-id", b"ws-req-00001") in list(accept.get("headers", []))  # type: ignore[call-overload]
    assert any(m["type"] == "websocket.send" and m.get("text") == "hello" for m in sent)


async def test_request_context_does_not_leak_after_response(
    client_factory: ClientFactory,
    offline_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with client_factory(offline_settings) as client:
        await client.get("/health/live", headers={"X-Request-ID": "leak-check-01"})
        get_logger("tests").info("outside_request")

    logs = _json_lines(capsys.readouterr().out)
    outside = next(line for line in logs if line["event"] == "outside_request")
    assert "request_id" not in outside
