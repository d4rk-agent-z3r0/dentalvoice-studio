from app.core.config import Settings
from tests.conftest import ClientFactory


async def test_live_returns_ok_without_database(
    client_factory: ClientFactory, offline_settings: Settings
) -> None:
    async with client_factory(offline_settings) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_returns_503_when_database_unreachable(
    client_factory: ClientFactory, offline_settings: Settings
) -> None:
    async with client_factory(offline_settings) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
