import pytest

from app.core.config import Settings
from tests.conftest import ClientFactory

pytestmark = pytest.mark.integration


async def test_ready_returns_ok_with_real_postgres(
    client_factory: ClientFactory, database_settings: Settings
) -> None:
    async with client_factory(database_settings) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
