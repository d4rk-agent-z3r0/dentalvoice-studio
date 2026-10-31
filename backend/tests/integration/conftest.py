# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Integration fixtures: a real PostgreSQL database migrated with Alembic (never create_all).

Tests isolate themselves by creating their own clinics with random slugs, so services can commit
for real and no test depends on another's data.
"""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database.session import create_session_factory
from app.models import Clinic
from tests.support import alembic
from tests.support.database import create_test_engine

ClinicFactory = Callable[..., Awaitable[Clinic]]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL must be set to run integration tests (see Makefile).")
    return url


@pytest.fixture(scope="session")
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_test_engine(test_database_url)
    async with engine.begin() as connection:
        await connection.run_sync(alembic.downgrade, "base")
        await connection.run_sync(alembic.upgrade, "head")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
def make_clinic(session_factory: async_sessionmaker[AsyncSession]) -> ClinicFactory:
    async def _make(name: str = "Test Clinic", timezone: str = "Europe/London") -> Clinic:
        clinic = Clinic(name=name, slug=f"test-{uuid.uuid4().hex[:12]}", timezone=timezone)
        async with session_factory.begin() as session:
            session.add(clinic)
        return clinic

    return _make
