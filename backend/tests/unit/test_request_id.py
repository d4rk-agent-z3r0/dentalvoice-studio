import uuid

from app.core.config import Settings
from tests.conftest import ClientFactory


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
        response = await client.get(
            "/health/live", headers={"X-Request-ID": "bad id\nwith newline"}
        )

    returned = response.headers["x-request-id"]
    assert returned != "bad id\nwith newline"
    uuid.UUID(returned)
