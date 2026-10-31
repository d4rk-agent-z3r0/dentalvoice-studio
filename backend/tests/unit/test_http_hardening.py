# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Response headers, request size limit, CORS and docs exposure. No database needed."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from app.middleware.body_limit import MAX_BODY_BYTES
from app.middleware.security_headers import API_CSP
from tests.conftest import UNREACHABLE_DATABASE_URL, ClientFactory, make_test_settings

ALLOWED = "http://localhost:3000"


@pytest.fixture
async def client(
    client_factory: ClientFactory, offline_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(offline_settings) as client:
        yield client


def _assert_hardened(response: httpx.Response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["content-security-policy"] == API_CSP


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/health/live", 200),
        ("GET", "/api/v1/clinic", 401),
        ("GET", "/api/v1/no-such-route", 404),
        ("DELETE", "/api/v1/auth/login", 405),
        ("POST", "/api/v1/auth/login", 400),
    ],
)
async def test_every_response_carries_the_defensive_headers(
    client: httpx.AsyncClient, method: str, path: str, status: int
) -> None:
    response = await client.request(method, path, json={} if method == "POST" else None)
    assert response.status_code == status
    if status >= 400:
        assert set(response.json()["error"]) >= {"code", "message", "request_id"}  # one shape
    _assert_hardened(response)
    assert response.headers["cache-control"] == "no-store"


async def test_a_route_that_chose_a_cache_policy_keeps_it(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={})
    assert response.headers["cache-control"] == "no-store"  # set by the route and the default
    assert API_CSP.startswith("default-src 'none'")


async def test_an_oversized_body_is_refused_before_it_is_read(client: httpx.AsyncClient) -> None:
    body = b'{"email": "' + b"a" * (MAX_BODY_BYTES + 1) + b'"}'
    response = await client.post(
        "/api/v1/auth/login",
        content=body,
        headers={"Content-Type": "application/json", "Origin": ALLOWED},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "PAYLOAD_TOO_LARGE"
    assert error["request_id"] == response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == ALLOWED  # readable by the app
    _assert_hardened(response)


async def test_a_chunked_body_is_counted_as_it_arrives(client: httpx.AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"email": "'
        for _ in range(MAX_BODY_BYTES // 1024 + 2):
            yield b"a" * 1024
        yield b'"}'

    response = await client.post(
        "/api/v1/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413


async def test_a_body_at_the_limit_is_accepted(client: httpx.AsyncClient) -> None:
    filler = "a" * (MAX_BODY_BYTES - 64)
    response = await client.post("/api/v1/auth/login", json={"email": filler})
    assert response.status_code == 400  # reached validation, not refused for size


async def test_cors_answers_only_the_configured_origin(client: httpx.AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    allowed = await client.options("/api/v1/auth/login", headers={"Origin": ALLOWED, **preflight})
    assert allowed.headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-credentials" not in allowed.headers
    other = await client.options(
        "/api/v1/auth/login", headers={"Origin": "https://evil.example.com", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers


@pytest.mark.parametrize(
    "origin",
    ["*", "http://localhost:3000/", "https://app.example.com/path", "localhost:3000", ""],
)
def test_cors_origins_must_be_exact(origin: str) -> None:
    with pytest.raises(ValidationError, match="exact origins"):
        make_test_settings(UNREACHABLE_DATABASE_URL, cors_origins=[origin])


async def test_api_docs_exist_in_development_without_the_api_csp(
    client: httpx.AsyncClient,
) -> None:
    docs = await client.get("/docs")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers  # Swagger UI needs its scripts
    assert docs.headers["x-frame-options"] == "DENY"


async def test_api_docs_are_disabled_in_production(client_factory: ClientFactory) -> None:
    settings = make_test_settings(UNREACHABLE_DATABASE_URL, environment=Environment.PRODUCTION)
    async with client_factory(settings) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = await client.get(path)
            assert response.status_code == 404, path
            _assert_hardened(response)


async def test_cross_origin_pages_can_read_the_headers_they_need(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/live", headers={"Origin": ALLOWED})
    exposed = {
        h.strip().lower() for h in response.headers["access-control-expose-headers"].split(",")
    }
    assert {"x-request-id", "retry-after", "idempotent-replayed"} <= exposed
