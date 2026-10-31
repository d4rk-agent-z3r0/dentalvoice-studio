# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""The conversation API: authentication, roles, clinic scoping and the error contract."""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.demo.seed import seed
from tests.conftest import ClientFactory, make_test_settings
from tests.support.api import DemoClinic, bearer, load_clinic, token_for

pytestmark = pytest.mark.integration

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def world(session_factory: SessionFactory) -> tuple[DemoClinic, DemoClinic]:
    await seed(session_factory, days=1)
    return (
        await load_clinic(session_factory, "brightsmile"),
        await load_clinic(session_factory, "juniper-vale"),
    )


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings, session_factory: SessionFactory
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


async def test_requests_without_a_valid_token_are_rejected(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/scenarios")
    garbage = await client.get("/api/v1/scenarios", headers=bearer("not-a-jwt"))

    assert missing.status_code == garbage.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
    assert garbage.json()["error"]["code"] == "AUTH_INVALID"
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert missing.json()["error"]["request_id"] == missing.headers["x-request-id"]


async def test_scenarios_come_from_the_tokens_clinic(
    client: httpx.AsyncClient,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, juniper = world
    admin = "demo.admin@example.com"  # member of both clinics
    for clinic in (bright, juniper):
        token = await token_for(session_factory, database_settings, admin, clinic.id)
        response = await client.get("/api/v1/scenarios", headers=bearer(token))
        assert {s["id"] for s in response.json()} == {str(i) for i in clinic.scenarios.values()}


async def test_start_turn_and_detail(
    client: httpx.AsyncClient,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, _ = world
    headers = bearer(
        await token_for(session_factory, database_settings, "demo.staff@example.com", bright.id)
    )
    created = await client.post(
        "/api/v1/conversations", json={"scenario_id": str(bright.scenarios["A"])}, headers=headers
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    url = f"/api/v1/conversations/{conversation_id}"

    early = await client.post(f"{url}/turns", json={"text": "hello"}, headers=headers)
    assert (early.status_code, early.json()["error"]["code"]) == (400, "INVALID_STATE_TRANSITION")

    started = await client.post(f"{url}/start", headers=headers)
    assert started.json()["state"] == "GREETING"
    assert "BrightSmile Dental Studio" in started.json()["reply"]

    turn = await client.post(
        f"{url}/turns",
        json={"text": "Hi, I'm a new patient. I'd like a cleaning."},
        headers=headers,
    )
    body = turn.json()
    assert body["path"] == ["INTRODUCTION", "IDENTITY_COLLECTION"]
    assert body["llm_ms"] is not None

    detail = (await client.get(url, headers=headers)).json()
    assert [t["speaker"] for t in detail["turns"]] == ["receptionist", "caller", "receptionist"]
    assert {d["field"]: d["value"] for d in detail["intake"]} == {
        "patient_type": "new",
        "requested_service": "hygiene_cleaning",
    }
    assert detail["snapshot"] is None
    assert detail["missing_fields"][:2] == ["first_name", "last_name"]

    ended = await client.post(f"{url}/end", headers=headers)
    again = await client.post(f"{url}/end", headers=headers)
    assert ended.json()["state"] == "ABANDONED"
    assert (again.status_code, again.json()["error"]["code"]) == (409, "CONVERSATION_CLOSED")


async def test_viewers_cannot_drive_conversations(
    client: httpx.AsyncClient,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, _ = world
    viewer = bearer(
        await token_for(session_factory, database_settings, "demo.viewer@example.org", bright.id)
    )
    response = await client.post(
        "/api/v1/conversations", json={"scenario_id": str(bright.scenarios["A"])}, headers=viewer
    )
    assert (response.status_code, response.json()["error"]["code"]) == (403, "FORBIDDEN")
    assert (await client.get("/api/v1/scenarios", headers=viewer)).status_code == 200


async def test_another_clinics_conversation_is_not_found(
    client: httpx.AsyncClient,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, juniper = world
    admin = "demo.admin@example.com"
    bright_headers = bearer(await token_for(session_factory, database_settings, admin, bright.id))
    juniper_headers = bearer(await token_for(session_factory, database_settings, admin, juniper.id))
    created = await client.post(
        "/api/v1/conversations",
        json={"scenario_id": str(bright.scenarios["A"])},
        headers=bright_headers,
    )
    url = f"/api/v1/conversations/{created.json()['id']}"

    for method, path in [("GET", ""), ("POST", "/start"), ("POST", "/end")]:
        response = await client.request(method, url + path, headers=juniper_headers)
        assert response.status_code == 404, (method, path)
    unknown = await client.get(f"/api/v1/conversations/{uuid.uuid4()}", headers=juniper_headers)
    assert unknown.json()["error"]["message"] == "Conversation not found."
    # Using another clinic's scenario id is also just "not found".
    cross = await client.post(
        "/api/v1/conversations",
        json={"scenario_id": str(bright.scenarios["A"])},
        headers=juniper_headers,
    )
    assert cross.status_code == 404


async def test_validation_errors_use_the_error_contract_without_echoing_input(
    client: httpx.AsyncClient,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, _ = world
    headers = bearer(
        await token_for(session_factory, database_settings, "demo.staff@example.com", bright.id)
    )
    response = await client.post(
        "/api/v1/conversations",
        json={"scenario_id": "secret-looking-value", "clinic_id": str(uuid.uuid4())},
        headers=headers,
    )
    body = response.json()
    assert (response.status_code, body["error"]["code"]) == (400, "VALIDATION_ERROR")
    assert "secret-looking-value" not in response.text
    # A client-supplied clinic id is not accepted anywhere: it is an unknown field.
    assert any(d["loc"][-1] == "clinic_id" for d in body["error"]["details"])


async def test_typed_turns_are_disabled_in_production(
    client_factory: ClientFactory,
    world: tuple[DemoClinic, DemoClinic],
    session_factory: SessionFactory,
    database_settings: Settings,
) -> None:
    bright, _ = world
    production = make_test_settings(
        str(database_settings.database_url), environment=Environment.PRODUCTION
    )
    headers = bearer(
        await token_for(session_factory, production, "demo.staff@example.com", bright.id)
    )
    async with client_factory(production) as client:
        created = await client.post(
            "/api/v1/conversations",
            json={"scenario_id": str(bright.scenarios["A"])},
            headers=headers,
        )
        url = f"/api/v1/conversations/{created.json()['id']}"
        await client.post(f"{url}/start", headers=headers)
        response = await client.post(f"{url}/turns", json={"text": "hi"}, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (403, "FORBIDDEN")
