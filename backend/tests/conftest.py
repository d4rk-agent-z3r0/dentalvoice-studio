"""Shared test fixtures."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from pydantic import PostgresDsn

from app.core.config import Environment, Settings
from app.main import create_app

# Port 1 on loopback is never a PostgreSQL server: connections are refused immediately.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"

ClientFactory = Callable[[Settings], AbstractAsyncContextManager[httpx.AsyncClient]]


@asynccontextmanager
async def _running_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def client_factory() -> ClientFactory:
    return _running_client


@pytest.fixture
def offline_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=PostgresDsn(UNREACHABLE_DATABASE_URL),
        db_connect_timeout_seconds=1.0,
    )


@pytest.fixture
def database_settings() -> Settings:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL must be set to run integration tests (see Makefile).")
    return Settings(environment=Environment.TEST, database_url=PostgresDsn(url))
