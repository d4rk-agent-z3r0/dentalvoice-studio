# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.demo.seed import seed
from tests.conftest import ClientFactory
from tests.support.api import bearer, load_clinic, token_for

pytestmark = pytest.mark.integration


@pytest.fixture
async def staff(
    session_factory: async_sessionmaker[AsyncSession], database_settings: Settings
) -> dict[str, str]:
    await seed(session_factory, days=1)
    clinic = await load_clinic(session_factory, "brightsmile")
    return bearer(
        await token_for(session_factory, database_settings, "demo.staff@example.com", clinic.id)
    )


@pytest.fixture
async def client(
    client_factory: ClientFactory, database_settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_factory(database_settings) as http:
        yield http


async def test_own_clinics_clip_is_served_as_wav(
    client: httpx.AsyncClient, staff: dict[str, str]
) -> None:
    response = await client.get("/api/v1/audio/clips/a-01", headers=staff)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-clip-source"] == "espeak-fixture"
    assert response.content[:4] == b"RIFF"


@pytest.mark.parametrize("clip_id", ["ja-01", "zz-99"])  # another clinic's clip; no such clip
async def test_other_clips_are_not_found(
    client: httpx.AsyncClient, staff: dict[str, str], clip_id: str
) -> None:
    response = await client.get(f"/api/v1/audio/clips/{clip_id}", headers=staff)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")


@pytest.mark.parametrize("clip_id", ["..%2Fmanifest.json", "a-01.wav", "A-01"])
async def test_path_like_ids_are_rejected(
    client: httpx.AsyncClient, staff: dict[str, str], clip_id: str
) -> None:
    response = await client.get(f"/api/v1/audio/clips/{clip_id}", headers=staff)
    assert response.status_code in (400, 404)
    assert response.headers["content-type"].startswith("application/json")


async def test_clips_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/audio/clips/a-01")).status_code == 401
